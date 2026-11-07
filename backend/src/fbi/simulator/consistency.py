"""The simulator against what the models in force stored for a day (``models.predictions``), and the incoherences in those numbers.

WHAT IS IN FORCE. For every fixture of the day (Bogotá, ``fbi.ai.calendar``) the newest REAL-TIME forecast of every model made at or
before the moment of the check (and never after kick-off): one version per model, the one that made that forecast - the same reading
as the pick engine's (``fbi.picks.engine._forecasts``). Backtest replays (``backtest_session_id``) are not in force.

WHERE THE SIMULATOR'S INPUTS COME FROM. ``models.predictions`` stores probabilities, not expected goals. A Poisson or Dixon-Coles row
set is an exact function of (lambda_home, lambda_away[, rho]) - the seven fixed rows of ``fbi.models.scoring.MARKET_ROWS`` (1X2, over
2.5, BTTS) are computed from the 10-10 score matrix - so those parameters are RECOVERED by solving the model's own equations on its own
seven rows (least squares on the same arithmetic, ``invert``). That is not a fit of anything new: with four independent numbers and
two or three unknowns the system is over-determined, and its residual is itself a check (a row set no parameters reproduce is
incoherent). The recovered parameters feed ``joint.build`` (halves by the documented split: no stored market depends on it), and every
OTHER stored row (the Asian handicaps, the double chance, the other over/under lines) is an independent comparison.

The Elo ordered logit states a 1X2 only: there are no goal intensities to simulate, and making them up from three numbers would be the
heuristic mapping the design rules out. Its 1X2 is compared ACROSS the models in force instead (``spread``).

INCOHERENCES. Within one version's rows (``incoherences``): the complementary outcomes add up to one (1X2, each over/under line, BTTS,
each Asian line pair, pushes included); the double chance and the 0 / +-0.5 handicaps are the sums of the 1X2; over/under and the
handicaps are monotone in the line; and the bounds that follow from what the events contain:

    BTTS yes - P(draw) <= over 2.5      (both scoring with two goals or fewer is 1-1, a draw)
    over 2.5 <= BTTS yes + P(home) + P(away)   (over 2.5 with a side on nil is not a draw)
    BTTS yes <= over 1.5,  under 1.5 <= BTTS no,  P(home) + P(away) <= over 0.5,  under 0.5 <= P(draw)

Read-only: SELECTs only; nothing here writes, decides or is read by anything that does.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from itertools import pairwise
from typing import Any, Final

import numpy as np
import psycopg
from numpy.typing import NDArray
from psycopg.rows import dict_row
from scipy.optimize import least_squares

from fbi.models.goals import dc_valid
from fbi.models.scoring import MARKET_ROWS, dc_tau, from_matrix, poisson_matrix
from fbi.simulator import VERSION
from fbi.simulator import joint as jt
from fbi.simulator.markets import Correlations, Selection

GOAL_MODELS: Final = frozenset({"poisson", "dixon_coles"})
"""The models in force whose rows are a function of goal intensities (``fbi.backtesting.persist.CATALOGUE`` registry names)."""

TOLERANCE: Final = 1e-5
"""Stored probabilities are rounded to 6 decimals; a sum of a few of them can be off by a few millionths without being incoherent."""

INVERSION_TOLERANCE: Final = 1e-4
"""Largest residual of the seven fixed rows at which the recovered intensities are taken as the model's own."""

SIMULATED_MARKETS: Final = frozenset({"1X2", "OU", "BTTS", "AH", "DC"})


@dataclass(frozen=True, slots=True)
class StoredRow:
    market_key: str
    selection: str
    line: float
    p: float
    p_push: float = 0.0


@dataclass(frozen=True, slots=True)
class Inversion:
    lam_home: float
    lam_away: float
    rho: float | None
    residual: float
    """Largest absolute difference on the seven fixed rows between the stored numbers and the model at the recovered parameters."""


@dataclass(frozen=True, slots=True)
class Diff:
    market_key: str
    selection: str
    line: float
    stored: float
    simulated: float
    stored_push: float
    simulated_push: float
    inversion_row: bool

    @property
    def abs_diff(self) -> float:
        return max(abs(self.simulated - self.stored), abs(self.simulated_push - self.stored_push))


@dataclass(frozen=True, slots=True)
class Incoherence:
    rule: str
    detail: str
    gap: float
    """How far past the tolerance the rule fails (always > 0)."""


def _fixed(rows: Iterable[StoredRow]) -> list[float] | None:
    by = {(r.market_key, r.selection, r.line): r.p for r in rows}
    out = [by.get((m, s, ln)) for m, s, ln in MARKET_ROWS]
    return None if any(v is None for v in out) else [float(v) for v in out if v is not None]


def _model_rows(lh: float, la: float, rho: float | None) -> NDArray[np.float64]:
    m = poisson_matrix(lh, la)
    if rho is not None:
        m = dc_tau(m, lh, la, rho)
    return np.array(from_matrix(m, lh, la).as_rows())


def invert(rows: Iterable[StoredRow], kind: str) -> Inversion | None:
    """The (lambda_home, lambda_away[, rho]) at which the source model's arithmetic gives its seven stored fixed rows; None without them."""
    target = _fixed(rows)
    if target is None or kind not in GOAL_MODELS:
        return None
    y = np.array(target)
    dc = kind == "dixon_coles"

    def resid(theta: NDArray[np.float64]) -> NDArray[np.float64]:
        lh, la = math.exp(theta[0]), math.exp(theta[1])
        rho = float(theta[2]) if dc else None
        if rho is not None and not dc_valid(lh, la, rho):
            return np.full(len(y), 10.0)
        return np.asarray(_model_rows(lh, la, rho) - y, dtype=np.float64)

    best: Any = None
    for start in ((1.4, 1.1), (1.0, 1.0), (2.2, 0.8), (0.8, 2.2)):
        x0 = [math.log(start[0]), math.log(start[1])] + ([0.0] if dc else [])
        fit = least_squares(resid, np.array(x0), xtol=1e-14, ftol=1e-14, gtol=1e-14, max_nfev=2000)
        if best is None or fit.cost < best.cost:
            best = fit
    theta = best.x
    lh, la = math.exp(float(theta[0])), math.exp(float(theta[1]))
    rho = float(theta[2]) if dc else None
    return Inversion(lh, la, rho, float(np.abs(resid(theta)).max()))


def selection_of(row: StoredRow) -> Selection | None:
    """The simulator's selection for a stored row, or None for a market the simulator does not derive."""
    if row.market_key not in SIMULATED_MARKETS:
        return None
    try:
        return Selection(row.market_key, row.selection, row.line, "FT")
    except ValueError:
        return None


def compare(joint: jt.JointScore, rows: Iterable[StoredRow]) -> list[Diff]:
    """Each stored row against the simulator's derivation of the same selection."""
    c = Correlations(joint)
    fixed = {(m, s, ln) for m, s, ln in MARKET_ROWS}
    out: list[Diff] = []
    for r in rows:
        sel = selection_of(r)
        if sel is None:
            continue
        lo = c.price(sel)
        out.append(Diff(r.market_key, r.selection, r.line, r.p, lo.win, r.p_push, lo.push, (r.market_key, r.selection, r.line) in fixed))
    return out


def summarise(diffs: Iterable[Diff]) -> dict[str, dict[str, Any]]:
    """Per market (the rows the intensities were recovered from apart): n, max and mean absolute difference."""
    by: dict[str, list[float]] = defaultdict(list)
    for d in diffs:
        by[f"{d.market_key} (inversion rows)" if d.inversion_row else d.market_key].append(d.abs_diff)
    return {k: {"n": len(v), "max_abs": max(v), "mean_abs": sum(v) / len(v)} for k, v in sorted(by.items())}


# -- incoherences within one version's rows -----------------------------------------------------------------------------------------------

def _close(rule: str, detail: str, value: float, expected: float, tol: float) -> Incoherence | None:
    gap = abs(value - expected) - tol
    return Incoherence(rule, f"{detail}: {value:.6f} vs {expected:.6f}", gap) if gap > 0 else None


def _at_most(rule: str, detail: str, left: float, right: float, tol: float) -> Incoherence | None:
    gap = left - right - tol
    return Incoherence(rule, f"{detail}: {left:.6f} > {right:.6f}", gap) if gap > 0 else None


def incoherences(rows: Sequence[StoredRow], *, tol: float = TOLERANCE) -> list[Incoherence]:
    """Every rule of the module docstring that one version's stored rows break."""
    p: dict[tuple[str, str, float], StoredRow] = {(r.market_key, r.selection, r.line): r for r in rows}

    def win(m: str, s: str, ln: float = 0.0) -> float | None:
        r = p.get((m, s, ln))
        return None if r is None else r.p

    found: list[Incoherence | None] = []
    h, d, a = win("1X2", "Home"), win("1X2", "Draw"), win("1X2", "Away")
    if h is not None and d is not None and a is not None:
        found.append(_close("1x2_sums_to_one", "Home + Draw + Away", h + d + a, 1.0, tol))
        for sel, expected in (("1X", h + d), ("X2", d + a), ("12", h + a)):
            v = win("DC", sel)
            if v is not None:
                found.append(_close("dc_is_1x2_sum", f"DC {sel}", v, expected, tol))
        for sel, ln, expected in (("Home", -0.5, h), ("Home", 0.5, h + d), ("Away", -0.5, a), ("Away", 0.5, a + d),
                                  ("Home", 0.0, h), ("Away", 0.0, a)):
            v = win("AH", sel, ln)
            if v is not None:
                found.append(_close("ah_matches_1x2", f"AH {sel} {ln:+g}", v, expected, tol))
        ah0 = p.get(("AH", "Home", 0.0))
        if ah0 is not None:
            found.append(_close("ah_push_is_draw", "AH Home 0 push", ah0.p_push, d, tol))
    by = win("BTTS", "Yes")
    bn = win("BTTS", "No")
    if by is not None and bn is not None:
        found.append(_close("btts_sums_to_one", "BTTS Yes + No", by + bn, 1.0, tol))
    lines = sorted({r.line for r in rows if r.market_key == "OU"})
    for ln in lines:
        o, u = p.get(("OU", "Over", ln)), p.get(("OU", "Under", ln))
        if o is not None and u is not None:
            found.append(_close("ou_sums_to_one", f"OU {ln:g} Over + Under + push", o.p + u.p + o.p_push, 1.0, tol))
            found.append(_close("ou_push_both_sides", f"OU {ln:g} push Over vs Under", o.p_push, u.p_push, tol))
    overs = [(ln, p[("OU", "Over", ln)].p) for ln in lines if ("OU", "Over", ln) in p]
    for (l1, p1), (l2, p2) in pairwise(overs):
        found.append(_at_most("ou_monotone", f"Over {l2:g} above Over {l1:g}", p2, p1, tol))
    for side in ("Home", "Away"):
        ah = sorted((r.line, r) for r in rows if r.market_key == "AH" and r.selection == side)
        for (l1, r1), (l2, r2) in pairwise(ah):
            found.append(_at_most("ah_monotone", f"AH {side} win at {l1:+g} above {l2:+g}", r1.p, r2.p, tol))
    ah_lines = sorted({r.line for r in rows if r.market_key == "AH" and r.selection == "Home"})
    for ln in ah_lines:
        home_side, away_side = p.get(("AH", "Home", ln)), p.get(("AH", "Away", -ln))
        if home_side is not None and away_side is not None:
            found.append(_close("ah_pair_sums_to_one", f"AH Home {ln:+g} + Away {-ln:+g} + push",
                                home_side.p + away_side.p + home_side.p_push, 1.0, tol))
    o25, o15, o05 = win("OU", "Over", 2.5), win("OU", "Over", 1.5), win("OU", "Over", 0.5)
    u15, u05 = win("OU", "Under", 1.5), win("OU", "Under", 0.5)
    if by is not None and d is not None and o25 is not None:
        found.append(_at_most("btts_over25_lower_bound", "BTTS Yes - Draw <= Over 2.5", by - d, o25, tol))
    if by is not None and h is not None and a is not None and o25 is not None:
        found.append(_at_most("btts_over25_upper_bound", "Over 2.5 <= BTTS Yes + Home + Away", o25, by + h + a, tol))
    if by is not None and o15 is not None:
        found.append(_at_most("btts_within_over15", "BTTS Yes <= Over 1.5", by, o15, tol))
    if bn is not None and u15 is not None:
        found.append(_at_most("under15_within_btts_no", "Under 1.5 <= BTTS No", u15, bn, tol))
    if h is not None and a is not None and o05 is not None:
        found.append(_at_most("decided_within_over05", "Home + Away <= Over 0.5", h + a, o05, tol))
    if d is not None and u05 is not None:
        found.append(_at_most("nil_nil_within_draw", "Under 0.5 <= Draw", u05, d, tol))
    return [f for f in found if f is not None]


def spread(by_model: Mapping[str, Sequence[StoredRow]]) -> list[dict[str, Any]]:
    """The same selection across the models in force: what each says and the largest gap (a disagreement, not an incoherence)."""
    seen: dict[tuple[str, str, float], dict[str, float]] = defaultdict(dict)
    for model, rows in by_model.items():
        for r in rows:
            seen[(r.market_key, r.selection, r.line)][model] = r.p
    out = []
    for (m, s, ln), values in sorted(seen.items()):
        if len(values) > 1:
            out.append({"market_key": m, "selection": s, "line": ln, "models": dict(sorted(values.items())),
                        "spread": max(values.values()) - min(values.values())})
    return out


# -- the day, from the database -----------------------------------------------------------------------------------------------------------

FIXTURES_SQL: Final = """
SELECT f.id AS fixture_id, f.kickoff_at, f.home_team_id, f.away_team_id
  FROM core.fixtures f
 WHERE f.kickoff_at >= %s AND f.kickoff_at < %s
 ORDER BY f.kickoff_at, f.id
"""

IN_FORCE_SQL: Final = """
WITH made AS (
    SELECT DISTINCT v.model_id, p.model_version_id, p.data_cutoff_ts
      FROM models.predictions p JOIN models.model_versions v ON v.id = p.model_version_id
     WHERE p.fixture_id = %(fixture)s AND p.backtest_session_id IS NULL AND p.data_cutoff_ts <= %(at)s
), newest AS (
    SELECT DISTINCT ON (model_id) model_id, model_version_id, data_cutoff_ts FROM made
     ORDER BY model_id, data_cutoff_ts DESC, model_version_id DESC
)
SELECT r.name AS model, n.model_version_id, n.data_cutoff_ts, p.market_key, p.selection, p.line, p.p_raw, p.p_push
  FROM newest n
  JOIN models.model_registry r ON r.id = n.model_id
  JOIN models.predictions p ON p.model_version_id = n.model_version_id AND p.data_cutoff_ts = n.data_cutoff_ts
 WHERE p.fixture_id = %(fixture)s AND p.backtest_session_id IS NULL
 ORDER BY r.name, p.market_key, p.selection, p.line
"""


@dataclass
class ModelForecast:
    model: str
    version_id: int
    data_cutoff_ts: datetime
    rows: list[StoredRow] = field(default_factory=list)


def in_force(conn: psycopg.Connection[Any], fixture_id: int, at: datetime) -> list[ModelForecast]:
    out: dict[str, ModelForecast] = {}
    with conn.cursor(row_factory=dict_row) as cur:
        for r in cur.execute(IN_FORCE_SQL, {"fixture": fixture_id, "at": at}).fetchall():
            mf = out.setdefault(str(r["model"]), ModelForecast(str(r["model"]), int(r["model_version_id"]), r["data_cutoff_ts"]))
            mf.rows.append(StoredRow(str(r["market_key"]), str(r["selection"]), float(r["line"]), float(r["p_raw"]),
                                     float(r["p_push"] or 0)))
    return list(out.values())


def check_model(mf: ModelForecast) -> dict[str, Any]:
    """One model's rows for one fixture: its incoherences and, for a goal model, the simulator against it."""
    doc: dict[str, Any] = {"model": mf.model, "version_id": mf.version_id, "data_cutoff_ts": mf.data_cutoff_ts.isoformat(),
                           "rows": len(mf.rows), "incoherences": [vars_of(i) for i in incoherences(mf.rows)]}
    if mf.model not in GOAL_MODELS:
        doc["status"] = "not_simulable"
        doc["reason"] = "no goal intensities (1X2 only): compared across the models in force, not simulated"
        return doc
    inv = invert(mf.rows, mf.model)
    if inv is None:
        doc["status"] = "not_invertible"
        doc["reason"] = "the seven fixed rows (1X2, OU 2.5, BTTS) are not all stored"
        return doc
    doc.update({"lambda_home": inv.lam_home, "lambda_away": inv.lam_away, "rho": inv.rho, "inversion_residual": inv.residual})
    if inv.residual > INVERSION_TOLERANCE:
        doc["status"] = "incoherent_fixed_rows"
        doc["reason"] = f"no intensities reproduce the seven fixed rows within {INVERSION_TOLERANCE:g}"
        doc["incoherences"].append({"rule": "fixed_rows_reproducible", "detail": f"best residual {inv.residual:.6f}",
                                    "gap": inv.residual - INVERSION_TOLERANCE})
        return doc
    try:
        sim = jt.build(jt.split_full_time(inv.lam_home, inv.lam_away), rho=inv.rho, source=f"{mf.model} (recovered, documented split)")
    except ValueError as exc:  # InvalidCorrectionError included
        doc["status"] = "not_simulable"
        doc["reason"] = str(exc)
        return doc
    diffs = compare(sim, mf.rows)
    doc.update({"status": "compared", "tail_mass": sim.tail_mass, "markets": summarise(diffs),
                "max_abs": max((x.abs_diff for x in diffs), default=0.0)})
    return doc


def vars_of(i: Incoherence) -> dict[str, Any]:
    return {"rule": i.rule, "detail": i.detail, "gap": i.gap}


def check_day(conn: psycopg.Connection[Any], day: date, *, now: datetime) -> dict[str, Any]:
    """The report of ``scripts/ia_simulator.py check``: every fixture of the day with stored predictions in force."""
    from fbi.ai.calendar import day_bounds

    start, end = day_bounds(day)
    with conn.cursor(row_factory=dict_row) as cur:
        fixtures = cur.execute(FIXTURES_SQL, (start, end)).fetchall()
    items: list[dict[str, Any]] = []
    market_diffs: dict[str, dict[str, list[tuple[int, float, float]]]] = defaultdict(lambda: defaultdict(list))
    n_incoherent = 0
    for f in fixtures:
        at = min(now, f["kickoff_at"])
        forecasts = in_force(conn, int(f["fixture_id"]), at)
        if not forecasts:
            continue
        models = [check_model(mf) for mf in forecasts]
        for m in models:
            n_incoherent += len(m["incoherences"])
            for market, s in m.get("markets", {}).items():
                market_diffs[m["model"]][market].append((s["n"], s["max_abs"], s["mean_abs"] * s["n"]))
        items.append({"fixture_id": int(f["fixture_id"]), "kickoff_at": f["kickoff_at"].isoformat(), "as_of": at.isoformat(),
                      "models": models, "spread": spread({mf.model: mf.rows for mf in forecasts})})
    summary = {model: {market: {"n": sum(n for n, _, _ in v), "max_abs": max(mx for _, mx, _ in v),
                                "mean_abs": sum(t for _, _, t in v) / sum(n for n, _, _ in v)}
                       for market, v in sorted(by.items())}
               for model, by in sorted(market_diffs.items())}
    return {"version": VERSION, "shadow": True, "day": day.isoformat(), "at": now.isoformat(),
            "constants": {"max_half_goals": jt.MAX_HALF_GOALS, "first_half_share_home": jt.FIRST_HALF_SHARE_HOME,
                          "first_half_share_away": jt.FIRST_HALF_SHARE_AWAY, "tolerance": TOLERANCE,
                          "inversion_tolerance": INVERSION_TOLERANCE},
            "fixtures_of_the_day": len(fixtures), "fixtures_with_predictions": len(items), "incoherences": n_incoherent,
            "markets": summary, "fixtures": items}
