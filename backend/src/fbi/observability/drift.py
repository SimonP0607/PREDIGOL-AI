"""Calibration drift and the trend of the closing-line value (``drift-v1``, Plan Maestro IA, P3: the observability rail).

REPORT ONLY. This module reads what production already stored and says OK / WATCH / DRIFT with its evidence. It writes nothing, calls
nothing, and nothing that decides, publishes or shows imports it: a calibrator is retired by ``fbi.intel.calibration.run_calibration`` and
by nothing here. An alert is a reason for a person to look, never a switch.

CALIBRATION DRIFT, per (market, model, calibrator, league segment), for every calibrator that is CHAMPION at the end of the day:

    population   the settled selections of ``fbi.intel.calibration`` (``SETTLED_SQL``: the last pick before kick-off of each
                 (match, market, selection, line, model), win or loss only) whose kick-off falls in the ``WINDOW_DAYS`` Bogotá days ending
                 on the day, AFTER the calibrator was promoted and after its ``known_at`` (strictly out of sample), settled before the
                 day ended. The calibrated probability is the calibrator's own (``calibration.apply_params``)
    segment      ``fbi.catalog.segments`` of the match's competition, plus ``all`` (every segment together)
    reference    what the calibrator's walk-forward said when it was fitted (``intel.calibrators.wf``): its ECE, and its log loss
                 against the de-vigged market's over the same selections - the evidence it was promoted on
    minimum      ``MIN_N`` selections in the cell; fewer is INSUFFICIENT and says how many there were - never an alert

    ECE rule     ECE has a floor that depends on the sample (ten bins of thirty selections are never exactly calibrated), so the window's
                 ECE is read against the ECE a PERFECTLY calibrated probability would show on the same selections: ``NULL_REPS``
                 outcomes drawn from the calibrated probabilities themselves (seeded, so a report is reproducible). The excess is the
                 window's ECE minus that null mean.
                     WATCH  ECE above the null's 95th percentile AND excess >= reference ECE + ``ECE_WATCH_MARGIN``
                     DRIFT  ECE above the null's 99th percentile AND excess >= reference ECE + ``ECE_DRIFT_MARGIN``
    log-loss     the log loss depends on the base rate of the population, so a segment's absolute log loss is not comparable with the
    rule         pooled reference. What is comparable is the calibrated probability's log loss MINUS the market's on the SAME
                 selections (the market is calibrated: ``fbi.intel.calibration``'s note), against the same gap at promotion. Per
                 selection ``d = loss_cal - loss_market``; drift = mean(d) - reference gap; z = drift / (sd(d) / sqrt(n)).
                     WATCH  drift >= ``GAP_WATCH_MARGIN`` and z >= ``Z_WATCH``
                     DRIFT  drift >= ``GAP_DRIFT_MARGIN`` and z >= ``Z_DRIFT``
    status       the worse of the two rules. The cell also reports the window's absolute log losses (calibrated, raw model,
                 market) and, for ``all``, whether ``run_calibration``'s own retirement test (``RETIRE_*``) would hold - as evidence

CLV TREND, per layer (``decision-v1``, ``decision-fam-v1``) and market family (``fbi.ai.contracts.mcp.family_of``; a market of no family is
its own): the newest decision of each selection before kick-off whose expected value - calibrated when it has one, raw otherwise - reached
``calibration.EV_RULE`` (the population of ``edge-gate-v1``: the selections the layer saw value in), with its settled CLV
(``intel.decision_outcomes.clv``, the one definition ``clv-v1`` of ``fbi.market.closing_value``). The mean CLV of the last
``CLV_RECENT_DAYS`` Bogotá days of kick-off is compared with the ``CLV_BASELINE_DAYS`` before them (Welch's z):

    minimum      ``CLV_MIN_RECENT`` recent and ``CLV_MIN_BASELINE`` baseline selections; fewer is INSUFFICIENT
    WATCH        recent - baseline <= -``CLV_WATCH_DROP`` and z <= -``Z_WATCH``
    DRIFT        recent - baseline <= -``CLV_DRIFT_DROP`` and z <= -``Z_DRIFT``

Every constant below is an ENGINEERING CHOICE written before any data was read, not a measurement and not a figure of the plan (the plan
asks for the alert, not its threshold), except ``WINDOW_DAYS`` and the ``RETIRE_*`` figures, which are ``fbi.intel.calibration``'s own.
Changing one is ``drift-v2``, never an edit."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Final

import numpy as np
import psycopg
from numpy.typing import NDArray
from psycopg.rows import dict_row

from fbi.ai.calendar import day_start, local_day
from fbi.ai.contracts.mcp import family_of
from fbi.catalog.segments import CompetitionFacts, segment_of
from fbi.core.decision_versions import DECISION_CORE, DECISION_FAMILIES
from fbi.intel import calibration, stats
from fbi.intel.calibration import Obs
from fbi.market import closing_value

VERSION: Final = "drift-v1"

OK: Final = "OK"
WATCH: Final = "WATCH"
DRIFT: Final = "DRIFT"
INSUFFICIENT: Final = "INSUFFICIENT"
"""Too few selections to say anything: listed with its count, never an alert."""
SEVERITY: Final = {INSUFFICIENT: 0, OK: 0, WATCH: 1, DRIFT: 2}
ALL: Final = "all"

WINDOW_DAYS: Final = calibration.RETIRE_WINDOW_DAYS
"""The rolling window: the 14 days ``run_calibration`` judges a champion's prospective evaluation over."""
MIN_N: Final = 300
"""Selections a cell needs. Engineering choice: 30 per ECE bin on average; below it one bad weekend is the whole signal."""
ECE_BINS: Final = 10
NULL_REPS: Final = 200
NULL_SEED: Final = 20261107
ECE_WATCH_Q: Final = 0.95
ECE_DRIFT_Q: Final = 0.99
ECE_WATCH_MARGIN: Final = 0.01
ECE_DRIFT_MARGIN: Final = 0.02
GAP_WATCH_MARGIN: Final = 0.01
GAP_DRIFT_MARGIN: Final = 0.02
Z_WATCH: Final = 2.0
Z_DRIFT: Final = 3.0

CLV_RECENT_DAYS: Final = 7
CLV_BASELINE_DAYS: Final = 28
CLV_MIN_RECENT: Final = 100
CLV_MIN_BASELINE: Final = 300
CLV_WATCH_DROP: Final = 0.01
CLV_DRIFT_DROP: Final = 0.02
CLV_LAYERS: Final = (DECISION_CORE, DECISION_FAMILIES)

_EPS: Final = 1e-12


def worst(statuses: Iterable[str]) -> str:
    out = OK
    for s in statuses:
        if SEVERITY[s] > SEVERITY[out]:
            out = s
    return out


def _r(x: float | None, places: int = 6) -> float | None:
    return None if x is None or math.isnan(x) or math.isinf(x) else round(x, places)


def _f(x: Any) -> float | None:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


# ── the reference a calibrator was promoted on ────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Reference:
    """A CHAMPION calibrator and what its walk-forward said when it was fitted (``intel.calibrators.wf``)."""

    calibrator_id: int
    market_key: str
    model_name: str
    method: str
    version: str
    params: Mapping[str, float]
    known_at: datetime
    promoted_at: datetime
    ece: float | None
    logloss: float | None
    logloss_market: float | None
    n: int | None

    @property
    def since(self) -> datetime:
        """Selections from this moment on are out of sample for it AND were judged with it."""
        return max(self.known_at, self.promoted_at)

    @property
    def gap(self) -> float | None:
        """Its log loss minus the market's, out of sample, at promotion."""
        if self.logloss is None or self.logloss_market is None:
            return None
        return self.logloss - self.logloss_market

    def as_json(self) -> dict[str, Any]:
        return {"calibrator_id": self.calibrator_id, "method": self.method, "version": self.version,
                "known_at": self.known_at.isoformat(), "promoted_at": self.promoted_at.isoformat(), "n": self.n,
                "ece": _r(self.ece), "logloss": _r(self.logloss), "logloss_market": _r(self.logloss_market),
                "gap_vs_market": _r(self.gap)}


def reference_of(row: Mapping[str, Any]) -> Reference:
    """A row of ``calibration.ROLES_SQL`` as a reference."""
    wf = dict(row.get("wf") or {})
    n = wf.get("n")
    return Reference(int(row["entity_id"]), str(row["market_key"]), str(row["model_name"]), str(row["method"]),
                     str(row["version"]), {k: float(v) for k, v in dict(row.get("params") or {}).items()}, row["known_at"],
                     row["at"], _f(wf.get("ece_cal")), _f(wf.get("logloss_cal")), _f(wf.get("logloss_market")),
                     None if n is None else int(n))


# ── one cell ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def null_ece(p: NDArray[np.float64], *, reps: int = NULL_REPS, seed: int = NULL_SEED) -> tuple[float, float, float]:
    """The ECE a perfectly calibrated probability shows on these selections: (mean, 95th, 99th percentile) over ``reps`` outcomes drawn
    from ``p`` itself. Seeded: the same selections give the same figures."""
    rng = np.random.default_rng(seed)
    sims = np.array([stats.ece((rng.random(p.size) < p).astype(np.float64), p, ECE_BINS) for _ in range(reps)])
    return float(sims.mean()), float(np.quantile(sims, ECE_WATCH_Q)), float(np.quantile(sims, ECE_DRIFT_Q))


def _losses(y: NDArray[np.float64], p: NDArray[np.float64]) -> NDArray[np.float64]:
    pv = np.clip(p, _EPS, 1 - _EPS)
    out: NDArray[np.float64] = -(y * np.log(pv) + (1 - y) * np.log(1 - pv))
    return out


@dataclass(frozen=True)
class Cell:
    """The verdict on one (market, model, calibrator, segment) over the window."""

    reference: Reference
    segment: str
    status: str
    n: int
    reasons: tuple[str, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)

    @property
    def subject(self) -> str:
        r = self.reference
        return f"{r.market_key}/{r.model_name}/calibrator {r.calibrator_id} ({r.method}, {r.version})/{self.segment}"

    def as_json(self) -> dict[str, Any]:
        r = self.reference
        return {"market_key": r.market_key, "model_name": r.model_name, "calibrator": r.as_json(), "segment": self.segment,
                "status": self.status, "n": self.n, "reasons": list(self.reasons), "metrics": dict(self.metrics)}


def assess(ref: Reference, segment: str, obs: Sequence[Obs]) -> Cell:
    """drift-v1 on the selections of one cell (already restricted to the window and to the calibrator's out-of-sample period)."""
    pairs = [(o, calibration.apply_params(ref.method, dict(ref.params), o.p_model, o.p_market)) for o in obs]
    kept = [(o, p) for o, p in pairs if p is not None]
    n = len(kept)
    if n < MIN_N:
        return Cell(ref, segment, INSUFFICIENT, n, (f"{n} settled selections in the window, {MIN_N} needed",), {"min_n": MIN_N})
    y = np.array([o.y for o, _ in kept], dtype=np.float64)
    pc = np.array([p for _, p in kept], dtype=np.float64)
    praw = np.array([o.p_model for o, _ in kept], dtype=np.float64)
    pm = np.array([o.p_market for o, _ in kept], dtype=np.float64)
    ll_cal, ll_raw, ll_mkt = stats.logloss(y, pc), stats.logloss(y, praw), stats.logloss(y, pm)
    ece_obs = stats.ece(y, pc, ECE_BINS)
    null_mean, null_q95, null_q99 = null_ece(pc)
    excess = ece_obs - null_mean
    metrics: dict[str, Any] = {
        "n": n, "hit_rate": _r(float(y.mean())), "mean_p_cal": _r(float(pc.mean())),
        "ece": _r(ece_obs), "ece_null_mean": _r(null_mean), "ece_null_q95": _r(null_q95), "ece_null_q99": _r(null_q99),
        "ece_excess": _r(excess), "ece_reference": _r(ref.ece),
        "logloss_cal": _r(ll_cal), "logloss_raw": _r(ll_raw), "logloss_market": _r(ll_mkt),
        "logloss_reference": _r(ref.logloss), "reliability": stats.reliability(y, pc, ECE_BINS)}
    statuses: list[str] = []
    reasons: list[str] = []

    if ref.ece is None:
        reasons.append("ECE rule not applied: the calibrator stored no walk-forward ECE")
    else:
        ece_status = OK
        if ece_obs > null_q99 and excess >= ref.ece + ECE_DRIFT_MARGIN:
            ece_status = DRIFT
        elif ece_obs > null_q95 and excess >= ref.ece + ECE_WATCH_MARGIN:
            ece_status = WATCH
        statuses.append(ece_status)
        if ece_status != OK:
            reasons.append(f"ECE {ece_obs:.4f} (perfect calibration here: {null_mean:.4f}, p95 {null_q95:.4f}, p99 {null_q99:.4f}); "
                           f"excess {excess:.4f} against {ref.ece:.4f} at promotion")
        metrics["ece_status"] = ece_status

    ref_gap = ref.gap
    if ref_gap is None:
        reasons.append("log-loss rule not applied: the calibrator stored no walk-forward log loss of the model or of the market")
    else:
        d = _losses(y, pc) - _losses(y, pm)
        gap = float(d.mean())
        sd = float(d.std(ddof=1)) if n > 1 else 0.0
        drift = gap - ref_gap
        z = drift / (sd / math.sqrt(n)) if sd > 0 else (math.inf if drift > 0 else 0.0)
        gap_status = OK
        if drift >= GAP_DRIFT_MARGIN and z >= Z_DRIFT:
            gap_status = DRIFT
        elif drift >= GAP_WATCH_MARGIN and z >= Z_WATCH:
            gap_status = WATCH
        statuses.append(gap_status)
        metrics |= {"gap_vs_market": _r(gap), "gap_reference": _r(ref_gap), "gap_drift": _r(drift), "gap_z": _r(z, 3),
                    "gap_status": gap_status}
        if gap_status != OK:
            reasons.append(f"log loss {gap:+.4f} against the market on the same selections, {ref_gap:+.4f} at promotion "
                           f"(drift {drift:+.4f}, z {z:.2f})")
    if segment == ALL and n >= calibration.RETIRE_MIN_N:
        metrics["retire_test_holds"] = bool(ece_obs > calibration.RETIRE_ECE or ll_cal > ll_raw)
        metrics["retire_test"] = (f"run_calibration retires a champion whose last {calibration.RETIRE_WINDOW_DAYS} days have "
                                  f">= {calibration.RETIRE_MIN_N} selections and ECE > {calibration.RETIRE_ECE} or log loss above "
                                  "the raw model's (from its stored daily evaluations, not from this report)")
    if not statuses:
        return Cell(ref, segment, INSUFFICIENT, n, tuple(reasons), metrics)
    return Cell(ref, segment, worst(statuses), n, tuple(reasons), metrics)


def cells_of(ref: Reference, obs: Sequence[Obs], segments: Mapping[int, str]) -> list[Cell]:
    """Every cell of one calibrator: ``all`` first, then each segment that has selections (``unknown`` when the match's competition
    could not be read)."""
    by_segment: dict[str, list[Obs]] = defaultdict(list)
    for o in obs:
        by_segment[segments.get(o.fixture_id, "unknown")].append(o)
    return [assess(ref, ALL, obs), *(assess(ref, s, xs) for s, xs in sorted(by_segment.items()))]


def in_window(obs: Iterable[Obs], ref: Reference, *, day: date) -> list[Obs]:
    first = day - timedelta(days=WINDOW_DAYS - 1)
    return [o for o in obs if (o.market_key, o.model_name) == (ref.market_key, ref.model_name) and o.kickoff_at >= ref.since
            and first <= o.day <= day]


# ── CLV trend ─────────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ClvTrend:
    layer: str
    family: str
    status: str
    recent_n: int
    baseline_n: int
    recent_mean: float | None = None
    baseline_mean: float | None = None
    delta: float | None = None
    z: float | None = None
    reasons: tuple[str, ...] = ()

    @property
    def subject(self) -> str:
        return f"{self.layer}/{self.family}"

    def as_json(self) -> dict[str, Any]:
        return {"layer": self.layer, "family": self.family, "status": self.status, "recent_n": self.recent_n,
                "baseline_n": self.baseline_n, "recent_mean_clv": _r(self.recent_mean), "baseline_mean_clv": _r(self.baseline_mean),
                "delta": _r(self.delta), "z": _r(self.z, 3), "reasons": list(self.reasons),
                "recent_quality": closing_value.quality(self.recent_mean)}


def clv_trend(layer: str, family: str, recent: Sequence[float], baseline: Sequence[float]) -> ClvTrend:
    """The recent mean CLV of a family against its baseline (see the module's note)."""
    nr, nb = len(recent), len(baseline)
    if nr < CLV_MIN_RECENT or nb < CLV_MIN_BASELINE:
        return ClvTrend(layer, family, INSUFFICIENT, nr, nb,
                        float(np.mean(recent)) if recent else None, float(np.mean(baseline)) if baseline else None,
                        reasons=(f"{nr} recent (needs {CLV_MIN_RECENT}) and {nb} baseline (needs {CLV_MIN_BASELINE}) selections",))
    r, b = np.array(recent, dtype=np.float64), np.array(baseline, dtype=np.float64)
    mr, mb = float(r.mean()), float(b.mean())
    delta = mr - mb
    se = math.sqrt(float(r.var(ddof=1)) / nr + float(b.var(ddof=1)) / nb)
    z = delta / se if se > 0 else (-math.inf if delta < 0 else 0.0)
    status = OK
    if delta <= -CLV_DRIFT_DROP and z <= -Z_DRIFT:
        status = DRIFT
    elif delta <= -CLV_WATCH_DROP and z <= -Z_WATCH:
        status = WATCH
    reasons = () if status == OK else (
        f"mean CLV {mr:+.4f} over the last {CLV_RECENT_DAYS} days (n={nr}) against {mb:+.4f} over the {CLV_BASELINE_DAYS} before "
        f"(n={nb}): {delta:+.4f}, z {z:.2f}",)
    return ClvTrend(layer, family, status, nr, nb, mr, mb, delta, z, reasons)


def family_label(market_key: str) -> str:
    return family_of(market_key) or market_key


def clv_trends(rows: Iterable[tuple[str, str, date, float]], *, day: date) -> list[ClvTrend]:
    """(layer, market, Bogotá day of kick-off, CLV) rows into one trend per (layer, family)."""
    recent_first = day - timedelta(days=CLV_RECENT_DAYS - 1)
    base_first = recent_first - timedelta(days=CLV_BASELINE_DAYS)
    recent: dict[tuple[str, str], list[float]] = defaultdict(list)
    base: dict[tuple[str, str], list[float]] = defaultdict(list)
    for layer, market, d, clv in rows:
        key = (layer, family_label(market))
        if recent_first <= d <= day:
            recent[key].append(clv)
        elif base_first <= d < recent_first:
            base[key].append(clv)
    return [clv_trend(k[0], k[1], recent.get(k, []), base.get(k, [])) for k in sorted(set(recent) | set(base))]


# ── the SQL (read-only) ───────────────────────────────────────────────────────────────────────────────────────────────

SEGMENTS_SQL: Final = """
SELECT f.id, c.name, c.competition_type, c.entity_scope, c.tier
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE f.id = ANY(%(ids)s)
"""

CLV_SQL: Final = """
SELECT DISTINCT ON (d.decision_version, d.fixture_id, d.market_key, d.selection, d.line)
       d.decision_version, d.market_key, d.kickoff_at, d.ev_cal, d.ev_raw, o.clv::float8 AS clv
  FROM intel.decisions d JOIN intel.decision_outcomes o ON o.decision_id = d.id
 WHERE d.decision_version = ANY(%(layers)s) AND d.kickoff_at >= %(since)s AND d.kickoff_at < %(until)s
   AND o.settled_at < %(until)s
 ORDER BY d.decision_version, d.fixture_id, d.market_key, d.selection, d.line, d.known_at DESC, d.id DESC
"""
"""The newest decision of each selection of each layer (every decision is before kick-off: a CHECK of the table), with its outcome. The
EV filter is applied after: it is on the newest decision, not on any of them."""


def segments(conn: psycopg.Connection[Any], fixture_ids: Iterable[int]) -> dict[int, str]:
    ids = sorted(set(fixture_ids))
    if not ids:
        return {}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(SEGMENTS_SQL, {"ids": ids})
        return {int(r["id"]): segment_of(CompetitionFacts(str(r["name"]), r["competition_type"], r["entity_scope"],
                                                          None if r["tier"] is None else int(r["tier"]))).value
                for r in cur.fetchall()}


def champions(conn: psycopg.Connection[Any], *, at: datetime) -> list[Reference]:
    """The CHAMPION calibrators at ``at`` (``calibration.ROLES_SQL``: the one definition of who that is)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(calibration.ROLES_SQL, {"at": at})
        return [reference_of(r) for r in cur.fetchall()]


@dataclass(frozen=True)
class DriftReport:
    day: date
    cutoff: datetime
    cells: tuple[Cell, ...]
    clv: tuple[ClvTrend, ...]

    def alerts(self) -> list[dict[str, Any]]:
        """Every cell and trend that is not OK or INSUFFICIENT, worst first, in the shape of ``scripts.ia_alerts``."""
        out: list[dict[str, Any]] = []
        for c in self.cells:
            if SEVERITY[c.status] > 0:
                out.append({"rule": "calibration_drift", "version": VERSION, "severity": c.status, "subject": c.subject,
                            "summary": "; ".join(c.reasons), "evidence": c.as_json()})
        for t in self.clv:
            if SEVERITY[t.status] > 0:
                out.append({"rule": "clv_trend", "version": VERSION, "severity": t.status, "subject": t.subject,
                            "summary": "; ".join(t.reasons), "evidence": t.as_json()})
        return sorted(out, key=lambda a: -SEVERITY[a["severity"]])

    def as_json(self) -> dict[str, Any]:
        return {"version": VERSION, "day": self.day.isoformat(), "cutoff": self.cutoff.isoformat(), "window_days": WINDOW_DAYS,
                "min_n": MIN_N, "calibration": [c.as_json() for c in self.cells], "clv_trend": [t.as_json() for t in self.clv],
                "insufficient": sum(1 for c in self.cells if c.status == INSUFFICIENT)
                + sum(1 for t in self.clv if t.status == INSUFFICIENT)}


def report(conn: psycopg.Connection[Any], *, day: date, at: datetime | None = None) -> DriftReport:
    """drift-v1 for the Bogotá day ``day``: what was known at its end (or at ``at``, if earlier). Reads only."""
    cutoff = day_start(day + timedelta(days=1))
    if at is not None and at < cutoff:
        cutoff = at
    refs = champions(conn, at=cutoff)
    obs = calibration.load_observations(conn, cutoff=cutoff, history=timedelta(days=WINDOW_DAYS + 2))
    windows = {r.calibrator_id: in_window(obs, r, day=day) for r in refs}
    segs = segments(conn, (o.fixture_id for xs in windows.values() for o in xs))
    cells = [c for r in refs for c in cells_of(r, windows[r.calibrator_id], segs)]
    since = day_start(day - timedelta(days=CLV_RECENT_DAYS + CLV_BASELINE_DAYS - 1))
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(CLV_SQL, {"layers": list(CLV_LAYERS), "since": since, "until": cutoff})
        rows = [(str(r["decision_version"]), str(r["market_key"]), local_day(r["kickoff_at"]), float(r["clv"]))
                for r in cur.fetchall()
                if r["clv"] is not None and _value_seen(r["ev_cal"], r["ev_raw"])]
    return DriftReport(day, cutoff, tuple(cells), tuple(clv_trends(rows, day=day)))


def _value_seen(ev_cal: Any, ev_raw: Any) -> bool:
    ev = _f(ev_cal) if ev_cal is not None else _f(ev_raw)
    return ev is not None and ev >= calibration.EV_RULE
