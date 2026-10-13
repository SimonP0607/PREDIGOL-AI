"""CAPA 2, last step: calibrate the model probability of a market, per (market, model) - ``cal-logit2-v1``.

WHY (audit of 13 Oct 2026, production, 72,453 settled shadow picks): on the selections the models flag, their
probability is 10-15 points too high in every market (OU: mean p_model 0.53 against a hit rate of 0.41), while the
de-vigged market is calibrated (ECE 0.01-0.03). A decision on an uncalibrated probability sees value everywhere and
loses (-4 % to -12 % flat ROI, -3 % to -7 % closing-line value).

THE CALIBRATOR. ``logit p_cal = a + b * logit(p_model) + c * logit(p_market)``, fitted by penalised Newton-Raphson
(``fbi.intel.stats``) on the settled candidates of the same (market, model): the LAST pick before kick-off of each
(match, market, selection, line, model) - one observation per selection -, win = 1, loss = 0 (pushes, voids and half
results are left out). It is conditional on the model having flagged the selection, which is exactly the population the
decision layer judges: the winner's curse of the selection is in the data it learns from. Two simpler challengers are
fitted beside it: ``platt`` (the model alone) and ``identity`` (the raw model, the reference).

NO LEAKAGE. A fit at ``known_at`` uses only selections whose match started and whose result was SETTLED before
``known_at`` (``settled_max < known_at`` is a constraint of ``intel.calibrators``). The method is validated by a
walk-forward over Bogotá days: for each day D, a fit on the days before D (settled before D began, 28-day window) scores
D's selections - those scores are out of sample.

THE GATES, fixed before any new result is seen (``calib-gate-v1``, ``edge-gate-v1``):

    calib-gate-v1  out of sample >= 1,500 selections over >= 5 days; log loss at least 0.005 below the raw model's;
                   ECE <= 0.03; log loss not above the de-vigged market's + 0.002 (otherwise the market alone is the
                   better probability and the model adds nothing)
    edge-gate-v1   the rule "calibrated EV >= 2 %" had, out of sample, >= 300 selections and a mean closing-line value
                   >= 0: only then may a decision of that market be APPROVED

Roles live in ``intel.promotions`` (append-only). A champion is replaced by a refit or another method only when the new
one passes the gate AND either improves the walk-forward log loss by >= 0.002 or the champion is more than seven days
old (periodic re-estimation of the same validated method). A champion whose prospective evaluation fails (ECE > 0.05 or
worse than the raw model over its last 14 days, >= 500 selections) is RETIRED: its market falls back to INVESTIGATION.
Never because of one day's results.
"""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import numpy as np
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.ai.calendar import day_start, local_day
from fbi.core.version import code_version
from fbi.intel import stats

VERSION = "cal-logit2-v1"
GATE_VERSION = "calib-gate-v1"
EDGE_GATE_VERSION = "edge-gate-v1"
METHODS = ("logit2", "platt", "identity")
WINDOW = timedelta(days=28)
HISTORY = timedelta(days=120)
MIN_TRAIN = 500
WF_MIN_PRIOR_DAYS = 3
L2 = 1.0

MIN_OOS_N = 1500
MIN_OOS_DAYS = 5
MIN_GAIN_VS_RAW = 0.005
MAX_ECE = 0.03
MAX_LOSS_VS_MARKET = 0.002
EV_RULE = 0.02
MIN_RULE_N = 300
MIN_RULE_CLV = 0.0
REPLACE_GAIN = 0.002
REFIT_EVERY = timedelta(days=7)
RETIRE_WINDOW_DAYS = 14
RETIRE_MIN_N = 500
RETIRE_ECE = 0.05

SETTLED_SQL = """
WITH last AS (
    SELECT DISTINCT ON (p.fixture_id, p.market_key, p.selection, p.line, r.name)
           p.id AS pick_id, p.fixture_id, f.kickoff_at, p.market_key, p.selection, p.line, r.name AS model_name,
           p.p_calibrated::float8 AS p_model, p.p_market_fair::float8 AS p_market, p.market_odds::float8 AS odds,
           pr.result_status, pr.settled_at, lv.lv_devigged::float8 AS clv
      FROM picks.picks p
      JOIN core.fixtures f ON f.id = p.fixture_id
      JOIN models.model_versions v ON v.id = p.model_version_id
      JOIN models.model_registry r ON r.id = v.model_id
      JOIN picks.pick_results pr ON pr.pick_id = p.id
      LEFT JOIN picks.pick_line_value lv ON lv.pick_id = p.id
     WHERE (%(market)s::text IS NULL OR p.market_key = %(market)s)
       AND f.kickoff_at >= %(since)s AND f.kickoff_at < %(cutoff)s
       AND p.created_at < f.kickoff_at
       AND pr.settled_at IS NOT NULL AND pr.settled_at < %(cutoff)s
     ORDER BY p.fixture_id, p.market_key, p.selection, p.line, r.name, p.created_at DESC, p.id DESC
)
SELECT * FROM last
 WHERE result_status IN ('win', 'loss') AND p_market IS NOT NULL AND p_market > 0 AND p_market < 1
   AND p_model > 0 AND p_model < 1
 ORDER BY kickoff_at, pick_id
"""


@dataclass(frozen=True, slots=True)
class Obs:
    pick_id: int
    fixture_id: int
    kickoff_at: datetime
    settled_at: datetime
    market_key: str
    model_name: str
    p_model: float
    p_market: float
    odds: float
    y: float
    clv: float | None

    @property
    def day(self) -> date:
        return local_day(self.kickoff_at)


def load_observations(conn: psycopg.Connection[Any], *, cutoff: datetime, market: str | None = None,
                      history: timedelta = HISTORY) -> list[Obs]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(SETTLED_SQL, {"market": market, "since": cutoff - history, "cutoff": cutoff})
        rows = cur.fetchall()
    return [Obs(int(r["pick_id"]), int(r["fixture_id"]), r["kickoff_at"], r["settled_at"], str(r["market_key"]),
                str(r["model_name"]), float(r["p_model"]), float(r["p_market"]), float(r["odds"]),
                1.0 if r["result_status"] == "win" else 0.0, None if r["clv"] is None else float(r["clv"]))
            for r in rows]


# ── the calibrator itself ────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Calibrator:
    market_key: str
    model_name: str
    method: str
    params: dict[str, float]
    id: int | None = None
    role: str | None = None

    def apply(self, p_model: float, p_market: float | None) -> float | None:
        """The calibrated probability, or None when the method needs a market price there is not."""
        return apply_params(self.method, self.params, p_model, p_market)


def apply_params(method: str, params: dict[str, float], p_model: float, p_market: float | None) -> float | None:
    if not (0 < p_model < 1):
        return None
    if method == "identity":
        return p_model
    lm = float(stats.logit(p_model))
    if method == "platt":
        z = params["a"] + params["b"] * lm
    elif method == "logit2":
        if p_market is None or not (0 < p_market < 1):
            return None
        z = params["a"] + params["b"] * lm + params["c"] * float(stats.logit(p_market))
    else:
        raise ValueError(f"unknown method {method}")
    p = float(stats.sigmoid(z))
    return min(max(p, 1e-4), 1 - 1e-4)


def fit_params(method: str, obs: list[Obs]) -> dict[str, float]:
    if method == "identity":
        return {}
    y = np.array([o.y for o in obs])
    lm = stats.logit(np.array([o.p_model for o in obs]))
    if method == "platt":
        m = stats.fit_logistic(lm.reshape(-1, 1), y, l2=L2)
        return {"a": round(m.w[0], 6), "b": round(m.w[1], 6)}
    lk = stats.logit(np.array([o.p_market for o in obs]))
    m = stats.fit_logistic(np.column_stack([lm, lk]), y, l2=L2)
    return {"a": round(m.w[0], 6), "b": round(m.w[1], 6), "c": round(m.w[2], 6)}


def train_set(obs: list[Obs], *, cutoff: datetime, window: timedelta | None = None) -> list[Obs]:
    """What a fit at ``cutoff`` may use: started and settled before it, inside the window."""
    window = WINDOW if window is None else window
    return [o for o in obs if o.settled_at < cutoff and o.kickoff_at < cutoff and o.kickoff_at >= cutoff - window]


def train_hash(obs: list[Obs]) -> str:
    return hashlib.sha256(",".join(str(o.pick_id) for o in sorted(obs, key=lambda o: o.pick_id)).encode()).hexdigest()


# ── walk-forward validation of a method ──────────────────────────────────────────────────────────────────────────

@dataclass
class WalkForward:
    method: str
    n: int = 0
    days: int = 0
    logloss_cal: float | None = None
    logloss_raw: float | None = None
    logloss_market: float | None = None
    brier_cal: float | None = None
    ece_cal: float | None = None
    ece_raw: float | None = None
    rule_n: int = 0
    rule_clv: float | None = None
    rule_clv_n: int = 0
    rule_roi: float | None = None
    rule_roi_ci: tuple[float, float] | None = None
    reliability: list[dict[str, Any]] = field(default_factory=list)
    per_day: list[dict[str, Any]] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        def r(x: float | None) -> float | None:
            return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(x, 6)
        return {"method": self.method, "n": self.n, "days": self.days, "logloss_cal": r(self.logloss_cal),
                "logloss_raw": r(self.logloss_raw), "logloss_market": r(self.logloss_market),
                "brier_cal": r(self.brier_cal), "ece_cal": r(self.ece_cal), "ece_raw": r(self.ece_raw),
                "rule_ev": EV_RULE, "rule_n": self.rule_n, "rule_clv": r(self.rule_clv), "rule_clv_n": self.rule_clv_n,
                "rule_roi": r(self.rule_roi),
                "rule_roi_ci": None if self.rule_roi_ci is None else [r(self.rule_roi_ci[0]), r(self.rule_roi_ci[1])],
                "reliability": self.reliability, "per_day": self.per_day}


def walk_forward(obs: list[Obs], method: str, *, until: date | None = None, window: timedelta | None = None,
                 min_train: int | None = None) -> WalkForward:
    """Each Bogotá day D scored by a fit on what was settled before D began (``window`` of kick-offs)."""
    window = WINDOW if window is None else window
    min_train = MIN_TRAIN if min_train is None else min_train
    by_day: dict[date, list[Obs]] = defaultdict(list)
    for o in obs:
        by_day[o.day].append(o)
    days = sorted(d for d in by_day if until is None or d <= until)
    ys: list[float] = []
    pc: list[float] = []
    pr: list[float] = []
    pk: list[float] = []
    take_clv: list[float] = []
    take_pnl: list[float] = []
    take_day: list[str] = []
    out = WalkForward(method)
    for i, d in enumerate(days):
        if i < WF_MIN_PRIOR_DAYS:
            continue
        cut = day_start(d)
        train = train_set(obs, cutoff=cut, window=window)
        if len(train) < min_train:
            continue
        params = fit_params(method, train)
        dy: list[float] = []
        dc: list[float] = []
        for o in by_day[d]:
            p = apply_params(method, params, o.p_model, o.p_market)
            if p is None:
                continue
            ys.append(o.y)
            pc.append(p)
            pr.append(o.p_model)
            pk.append(o.p_market)
            dy.append(o.y)
            dc.append(p)
            if p * o.odds - 1 >= EV_RULE:
                take_pnl.append((o.odds - 1) if o.y == 1 else -1.0)
                take_day.append(d.isoformat())
                if o.clv is not None:
                    take_clv.append(o.clv)
        if dy:
            out.per_day.append({"day": d.isoformat(), "n": len(dy), "n_train": len(train),
                                "logloss_cal": round(stats.logloss(np.array(dy), np.array(dc)), 5),
                                "params": params})
    if not ys:
        return out
    y, c, r_, k = np.array(ys), np.array(pc), np.array(pr), np.array(pk)
    out.n, out.days = len(ys), len(out.per_day)
    out.logloss_cal, out.logloss_raw, out.logloss_market = stats.logloss(y, c), stats.logloss(y, r_), stats.logloss(y, k)
    out.brier_cal = stats.brier(y, c)
    out.ece_cal, out.ece_raw = stats.ece(y, c), stats.ece(y, r_)
    out.reliability = stats.reliability(y, c)
    out.rule_n = len(take_pnl)
    if take_pnl:
        out.rule_roi = float(np.mean(take_pnl))
        out.rule_roi_ci = stats.bootstrap_mean_ci(np.array(take_pnl), np.array(take_day))
    if take_clv:
        out.rule_clv, out.rule_clv_n = float(np.mean(take_clv)), len(take_clv)
    return out


@dataclass(frozen=True, slots=True)
class GateVerdict:
    calibrated: bool
    edge: bool
    checks: dict[str, Any]


def gate(wf: WalkForward) -> GateVerdict:
    """calib-gate-v1 and edge-gate-v1 on a walk-forward evaluation (see the module's note)."""
    def ok(x: float | None, test: bool) -> bool:
        return x is not None and not math.isnan(x) and test

    llc, llr, llm = wf.logloss_cal, wf.logloss_raw, wf.logloss_market
    checks: dict[str, Any] = {
        "n_oos": {"value": wf.n, "min": MIN_OOS_N, "ok": wf.n >= MIN_OOS_N},
        "days_oos": {"value": wf.days, "min": MIN_OOS_DAYS, "ok": wf.days >= MIN_OOS_DAYS},
        "gain_vs_raw": {"value": None if llc is None or llr is None else round(llr - llc, 6),
                        "min": MIN_GAIN_VS_RAW,
                        "ok": ok(llc, llc is not None and llr is not None and llr - llc >= MIN_GAIN_VS_RAW)},
        "ece": {"value": None if wf.ece_cal is None else round(wf.ece_cal, 6), "max": MAX_ECE,
                "ok": ok(wf.ece_cal, wf.ece_cal is not None and wf.ece_cal <= MAX_ECE)},
        "vs_market": {"value": None if llc is None or llm is None else round(llc - llm, 6), "max": MAX_LOSS_VS_MARKET,
                      "ok": ok(llc, llc is not None and llm is not None and llc - llm <= MAX_LOSS_VS_MARKET)},
    }
    calibrated = all(v["ok"] for v in checks.values())
    edge_checks: dict[str, dict[str, Any]] = {
        "rule_n": {"value": wf.rule_n, "min": MIN_RULE_N, "ok": wf.rule_n >= MIN_RULE_N},
        "rule_clv": {"value": None if wf.rule_clv is None else round(wf.rule_clv, 6), "min": MIN_RULE_CLV,
                     "ok": wf.rule_clv is not None and wf.rule_clv >= MIN_RULE_CLV and wf.rule_clv_n >= MIN_RULE_N},
    }
    checks["edge"] = edge_checks
    edge = calibrated and all(v["ok"] for v in edge_checks.values())
    return GateVerdict(calibrated, edge, checks)


# ── persistence and roles ────────────────────────────────────────────────────────────────────────────────────────

ROLES_SQL = """
SELECT DISTINCT ON (p.market_key, p.model_name) p.market_key, p.model_name, p.entity_id, p.to_role, p.at,
       c.method, c.params, c.known_at, c.wf, c.gate, c.version
  FROM intel.promotions p JOIN intel.calibrators c ON c.id = p.entity_id
 WHERE p.entity = 'calibrator' AND p.to_role = 'CHAMPION' AND p.at <= %(at)s
   AND NOT EXISTS (SELECT 1 FROM intel.promotions q
                    WHERE q.entity = 'calibrator' AND q.entity_id = p.entity_id AND q.to_role = 'RETIRED'
                      AND q.at >= p.at AND q.at <= %(at)s)
 ORDER BY p.market_key, p.model_name, p.at DESC, p.id DESC
"""

LATEST_FIT_SQL = """
WITH latest AS (
    SELECT market_key, model_name, max(known_at) AS k FROM intel.calibrators WHERE known_at <= %(at)s GROUP BY 1, 2
)
SELECT DISTINCT ON (c.market_key, c.model_name) c.id, c.market_key, c.model_name, c.method, c.params, c.known_at,
       c.wf, c.gate, c.version
  FROM intel.calibrators c
  JOIN latest l ON l.market_key = c.market_key AND l.model_name = c.model_name AND l.k = c.known_at
 WHERE c.method <> 'identity'
 ORDER BY c.market_key, c.model_name, (c.wf->>'logloss_cal')::float8 NULLS LAST, c.id
"""
"""Without a champion, the best method of the newest fit batch: what INVESTIGATION shows, never what approves."""

EDGE_SQL = """
SELECT DISTINCT ON (market_key, model_name) market_key, model_name, to_role, at, criteria
  FROM intel.promotions WHERE entity = 'market_edge' AND at <= %(at)s
 ORDER BY market_key, model_name, at DESC, id DESC
"""


@dataclass(frozen=True)
class CalibrationState:
    """What the decision layer reads at ``at``: per (market, model) the champion (if any), the best fit otherwise, and
    whether the market's edge is validated."""

    champions: dict[tuple[str, str], Calibrator]
    best: dict[tuple[str, str], Calibrator]
    wf: dict[tuple[str, str], dict[str, Any]]
    edge: dict[tuple[str, str], bool]

    def for_model(self, market: str, model: str) -> Calibrator | None:
        return self.champions.get((market, model)) or self.best.get((market, model))

    def primary_model(self, market: str, available: list[str]) -> str | None:
        """The market's specialised model among ``available``: the one whose champion calibrator has the lowest
        walk-forward log loss; without champions, the lowest among the fits; else the first available."""
        def loss(m: str) -> float:
            v = (self.wf.get((market, m)) or {}).get("logloss_cal")
            return float(v) if v is not None else math.inf
        champs = [m for m in available if (market, m) in self.champions]
        if champs:
            return min(champs, key=loss)
        fitted = [m for m in available if (market, m) in self.best]
        if fitted:
            return min(fitted, key=loss)
        return available[0] if available else None


def calibration_state(conn: psycopg.Connection[Any], *, at: datetime) -> CalibrationState:
    champions: dict[tuple[str, str], Calibrator] = {}
    best: dict[tuple[str, str], Calibrator] = {}
    wf: dict[tuple[str, str], dict[str, Any]] = {}
    edge: dict[tuple[str, str], bool] = {}
    try:
        with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            cur.execute(ROLES_SQL, {"at": at})
            for r in cur.fetchall():
                key = (str(r["market_key"]), str(r["model_name"]))
                champions[key] = Calibrator(key[0], key[1], str(r["method"]), dict(r["params"] or {}),
                                            int(r["entity_id"]), "CHAMPION")
                wf[key] = dict(r["wf"] or {})
            cur.execute(LATEST_FIT_SQL, {"at": at})
            for r in cur.fetchall():
                key = (str(r["market_key"]), str(r["model_name"]))
                best[key] = Calibrator(key[0], key[1], str(r["method"]), dict(r["params"] or {}), int(r["id"]),
                                       "CHALLENGER")
                wf.setdefault(key, dict(r["wf"] or {}))
            cur.execute(EDGE_SQL, {"at": at})
            for r in cur.fetchall():
                edge[(str(r["market_key"]), str(r["model_name"]))] = r["to_role"] == "VALIDATED"
    except psycopg.errors.UndefinedTable:
        pass
    return CalibrationState(champions, best, wf, edge)


def store_fit(conn: psycopg.Connection[Any], *, market: str, model: str, method: str, params: dict[str, float],
              known_at: datetime, fitted_at: datetime, train: list[Obs], wf: WalkForward, verdict: GateVerdict) -> int:
    settled_max = max((o.settled_at for o in train), default=None)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO intel.calibrators (market_key, model_name, method, version, params, known_at, fitted_at, "
            "train_from, train_to, n_train, train_hash, settled_max, wf, gate, code_version) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (market_key, model_name, method, version, known_at) DO NOTHING RETURNING id",
            (market, model, method, VERSION, Jsonb(params), known_at, fitted_at,
             min((o.day for o in train), default=None), max((o.day for o in train), default=None), len(train),
             train_hash(train), settled_max, Jsonb(wf.as_json()),
             Jsonb({"calibrated": verdict.calibrated, "edge": verdict.edge, "checks": verdict.checks,
                    "versions": [GATE_VERSION, EDGE_GATE_VERSION]}), code_version()))
        row = cur.fetchone()
        if row is not None:
            return int(row[0])
        cur.execute("SELECT id FROM intel.calibrators WHERE market_key=%s AND model_name=%s AND method=%s AND "
                    "version=%s AND known_at=%s", (market, model, method, VERSION, known_at))
        found = cur.fetchone()
        assert found is not None
        return int(found[0])


def promote(conn: psycopg.Connection[Any], *, at: datetime, entity: str, market: str, model: str,
            entity_id: int | None, from_role: str | None, to_role: str, gate_version: str, criteria: dict[str, Any],
            reason: str) -> None:
    with conn.cursor() as cur:
        cur.execute("INSERT INTO intel.promotions (at, entity, market_key, model_name, entity_id, from_role, to_role, "
                    "gate_version, criteria, reason, decided_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'system')",
                    (at, entity, market, model, entity_id, from_role, to_role, gate_version, Jsonb(criteria),
                     reason[:500]))


@dataclass
class CalibrationReport:
    fitted: int = 0
    promoted: list[str] = field(default_factory=list)
    retired: list[str] = field(default_factory=list)
    edge_changes: list[str] = field(default_factory=list)
    evaluations: int = 0
    summary: dict[str, Any] = field(default_factory=dict)


def _champion_rows(conn: psycopg.Connection[Any], at: datetime) -> dict[tuple[str, str], dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(ROLES_SQL, {"at": at})
        return {(str(r["market_key"]), str(r["model_name"])): dict(r) for r in cur.fetchall()}


def evaluate_prospective(conn: psycopg.Connection[Any], obs: list[Obs], *, at: datetime) -> int:
    """Score every calibrator on each finished Bogotá day after its known_at that it has not been scored on yet
    (out of sample by construction). Returns how many evaluations were written."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT c.id, c.market_key, c.model_name, c.method, c.params, c.known_at, "
                    "max(e.day) AS last_day FROM intel.calibrators c "
                    "LEFT JOIN intel.calibrator_evaluations e ON e.calibrator_id = c.id "
                    "WHERE c.known_at >= %s GROUP BY c.id", (at - timedelta(days=60),))
        cals = cur.fetchall()
    by_key: dict[tuple[str, str], list[Obs]] = defaultdict(list)
    for o in obs:
        by_key[(o.market_key, o.model_name)].append(o)
    today = local_day(at)
    written = 0
    with conn.cursor() as cur:
        for c in cals:
            start = local_day(c["known_at"]) if c["last_day"] is None else c["last_day"] + timedelta(days=1)
            days: dict[date, list[Obs]] = defaultdict(list)
            for o in by_key.get((str(c["market_key"]), str(c["model_name"])), []):
                # strictly after what the calibrator knew, and only whole days that are over
                if o.kickoff_at >= c["known_at"] and start <= o.day < today:
                    days[o.day].append(o)
            for d, xs in sorted(days.items()):
                ps = [apply_params(str(c["method"]), dict(c["params"] or {}), o.p_model, o.p_market) for o in xs]
                pairs = [(o, p) for o, p in zip(xs, ps, strict=True) if p is not None]
                if not pairs:
                    continue
                y = np.array([o.y for o, _ in pairs])
                pc = np.array([p for _, p in pairs])
                praw = np.array([o.p_model for o, _ in pairs])
                pm = np.array([o.p_market for o, _ in pairs])
                take = [(o, p) for o, p in pairs if p * o.odds - 1 >= EV_RULE]
                clvs = [o.clv for o, _ in take if o.clv is not None]
                pnl = [(o.odds - 1) if o.y == 1 else -1.0 for o, _ in take]
                cur.execute(
                    "INSERT INTO intel.calibrator_evaluations (calibrator_id, day, evaluated_at, n, logloss_cal, "
                    "logloss_raw, logloss_market, brier_cal, brier_raw, brier_market, ece_cal, ece_raw, rule_n, "
                    "rule_clv, rule_roi) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (calibrator_id, day) DO NOTHING",
                    (int(c["id"]), d, at, len(pairs), _r(stats.logloss(y, pc)), _r(stats.logloss(y, praw)),
                     _r(stats.logloss(y, pm)), _r(stats.brier(y, pc)), _r(stats.brier(y, praw)), _r(stats.brier(y, pm)),
                     _r(stats.ece(y, pc)), _r(stats.ece(y, praw)), len(take),
                     _r(float(np.mean(clvs))) if clvs else None, _r(float(np.mean(pnl))) if pnl else None))
                written += max(cur.rowcount, 0)
    return written


def _r(x: float | None) -> Decimal | None:
    if x is None or math.isnan(x):
        return None
    return Decimal(str(round(x, 6)))


PROSPECTIVE_SQL = """
SELECT sum(n) AS n, sum(n * logloss_cal) / NULLIF(sum(n), 0) AS ll_cal, sum(n * logloss_raw) / NULLIF(sum(n), 0) AS ll_raw,
       sum(n * ece_cal) / NULLIF(sum(n), 0) AS ece_cal
  FROM intel.calibrator_evaluations WHERE calibrator_id = %(id)s AND day >= %(since)s
"""


def run_calibration(conn: psycopg.Connection[Any], *, at: datetime, markets: list[str] | None = None,
                    force_refit: bool = False, commit: bool = True) -> CalibrationReport:
    """The nightly calibration step: prospective evaluation of every calibrator, a refit of each (market, model)
    with its walk-forward validation, promotion / retirement by the gates, the market-edge verdicts. Commits per
    (market, model)."""
    report = CalibrationReport()

    def _commit() -> None:
        if commit:
            conn.commit()

    obs = load_observations(conn, cutoff=at)
    report.evaluations = evaluate_prospective(conn, obs, at=at)
    _commit()
    groups: dict[tuple[str, str], list[Obs]] = defaultdict(list)
    for o in obs:
        if markets is None or o.market_key in markets:
            groups[(o.market_key, o.model_name)].append(o)
    champions = _champion_rows(conn, at)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(EDGE_SQL, {"at": at})
        edge_now = {(str(r["market_key"]), str(r["model_name"])): r["to_role"] for r in cur.fetchall()}
    for key, xs in sorted(groups.items()):
        market, model = key
        train = train_set(xs, cutoff=at)
        champ = champions.get(key)
        summary: dict[str, Any] = {"n_obs": len(xs), "n_train": len(train)}
        # retirement on prospective evidence
        if champ is not None:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(PROSPECTIVE_SQL, {"id": champ["entity_id"],
                                              "since": local_day(at) - timedelta(days=RETIRE_WINDOW_DAYS)})
                pr = cur.fetchone() or {}
            n = int(pr.get("n") or 0)
            if n >= RETIRE_MIN_N and pr.get("ll_cal") is not None and (
                    float(pr["ece_cal"]) > RETIRE_ECE or float(pr["ll_cal"]) > float(pr["ll_raw"])):
                promote(conn, at=at, entity="calibrator", market=market, model=model,
                        entity_id=int(champ["entity_id"]), from_role="CHAMPION", to_role="RETIRED",
                        gate_version=GATE_VERSION, criteria={"prospective": {k: (None if v is None else float(v))
                                                                             for k, v in pr.items()}},
                        reason=f"prospective evaluation over {RETIRE_WINDOW_DAYS} days failed "
                               f"(n={n}, ECE={float(pr['ece_cal']):.4f}, log loss {float(pr['ll_cal']):.4f} "
                               f"vs raw {float(pr['ll_raw']):.4f})")
                report.retired.append(f"{market}/{model}")
                champ = None
        stale = champ is None or (at - champ["at"]) >= REFIT_EVERY
        if len(train) < MIN_TRAIN or not (stale or force_refit):
            summary["refit"] = False
            report.summary[f"{market}/{model}"] = summary
            _commit()
            continue
        fits: list[tuple[str, dict[str, float], WalkForward, GateVerdict, int]] = []
        for method in METHODS:
            wf = walk_forward(xs, method)
            verdict = gate(wf)
            params = fit_params(method, train)
            cid = store_fit(conn, market=market, model=model, method=method, params=params, known_at=at, fitted_at=at,
                            train=train, wf=wf, verdict=verdict)
            report.fitted += 1
            fits.append((method, params, wf, verdict, cid))
        summary["fits"] = {m: {"logloss_cal": None if w.logloss_cal is None else round(w.logloss_cal, 5),
                               "logloss_raw": None if w.logloss_raw is None else round(w.logloss_raw, 5),
                               "logloss_market": None if w.logloss_market is None else round(w.logloss_market, 5),
                               "ece": None if w.ece_cal is None else round(w.ece_cal, 4), "n": w.n, "days": w.days,
                               "calibrated": v.calibrated, "edge": v.edge, "rule_n": w.rule_n,
                               "rule_clv": None if w.rule_clv is None else round(w.rule_clv, 4)}
                           for m, _, w, v, _ in fits}
        passing = [f for f in fits if f[0] != "identity" and f[3].calibrated and f[2].logloss_cal is not None]
        best = min(passing, key=lambda f: float(f[2].logloss_cal or math.inf)) if passing else None
        if best is not None:
            method, _, wf, verdict, cid = best
            champ_loss = None if champ is None else (champ.get("wf") or {}).get("logloss_cal")
            better = champ_loss is None or float(wf.logloss_cal or math.inf) <= float(champ_loss) - REPLACE_GAIN
            same_method_refit = champ is not None and champ.get("method") == method and stale
            if champ is None or better or same_method_refit:
                promote(conn, at=at, entity="calibrator", market=market, model=model, entity_id=cid,
                        from_role=None if champ is None else "CHALLENGER", to_role="CHAMPION",
                        gate_version=GATE_VERSION, criteria=verdict.checks,
                        reason=("first champion" if champ is None else
                                "better walk-forward log loss" if better else "periodic refit of the validated method")
                        + f": {method}, log loss {wf.logloss_cal:.4f} (raw {wf.logloss_raw:.4f}, market "
                          f"{wf.logloss_market:.4f}), ECE {wf.ece_cal:.4f}, n={wf.n} over {wf.days} days")
                if champ is not None:
                    promote(conn, at=at, entity="calibrator", market=market, model=model,
                            entity_id=int(champ["entity_id"]), from_role="CHAMPION", to_role="RETIRED",
                            gate_version=GATE_VERSION, criteria={"replaced_by": cid},
                            reason=f"replaced by calibrator {cid}")
                report.promoted.append(f"{market}/{model}:{method}")
                edge_ok = verdict.edge
            else:
                edge_ok = bool((champ.get("gate") or {}).get("edge"))
        else:
            # no method passes: record the best non-identity fit as a challenger, nothing promoted
            cands = [f for f in fits if f[0] != "identity" and f[2].logloss_cal is not None]
            if cands:
                method, _, wf, verdict, cid = min(cands, key=lambda f: float(f[2].logloss_cal or math.inf))
                promote(conn, at=at, entity="calibrator", market=market, model=model, entity_id=cid, from_role=None,
                        to_role="CHALLENGER", gate_version=GATE_VERSION, criteria=verdict.checks,
                        reason=f"best fit {method} does not pass {GATE_VERSION}: "
                               + ", ".join(k for k, v in verdict.checks.items() if k != "edge" and not v["ok"]))
            edge_ok = False if champ is None else bool((champ.get("gate") or {}).get("edge"))
        edge_role = "VALIDATED" if edge_ok else "NOT_VALIDATED"
        if edge_now.get(key) != edge_role:
            src = best or (min([f for f in fits if f[0] != "identity"], key=lambda f: float(f[2].logloss_cal or math.inf))
                           if fits else None)
            promote(conn, at=at, entity="market_edge", market=market, model=model,
                    entity_id=None if src is None else src[4], from_role=edge_now.get(key), to_role=edge_role,
                    gate_version=EDGE_GATE_VERSION,
                    criteria={} if src is None else src[3].checks.get("edge", {}),
                    reason=("calibrated EV >= 2 % beat the closing line out of sample" if edge_ok else
                            "no out-of-sample evidence that calibrated EV beats the closing line"))
            report.edge_changes.append(f"{market}/{model}:{edge_role}")
        report.summary[f"{market}/{model}"] = summary
        _commit()
    return report
