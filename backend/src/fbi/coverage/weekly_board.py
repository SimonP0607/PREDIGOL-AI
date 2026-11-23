"""The weekly private evaluation board: PrediGol's forecast, the market and the provider on the same matches (plan PM, PM-12-01).
``weekly-board-v1``. PRIVATE, and it decides nothing.

What the board lacked (AD-K02 to AD-K04 measure selections, «when there is a sample»): the reliability and the resolution of a forecast
apart, and the forecast set against the market and the provider. For the last whole week (Monday to Sunday, Bogotá) and for everything
since ``segments.FIRST_DAY``, and for each market (1X2, over/under 2.5, both teams to score), three sources on THE SAME matches:

* ``modelo``     PrediGol's forecast as a reader is shown it: the newest ``forecast-v1`` set before kick-off (``fbi.coverage.model_segments``);
* ``mercado``    the market's fair probability: the newest ``market.market_consensus`` set (Shin) before kick-off, every selection;
* ``proveedor``  API-Football's own forecast (``core.provider_predictions``, the newest before kick-off): 1X2 only, its three percents
                 over their sum. Auxiliary and labelled as the provider's: never a model input, never a pick.

THE MEASURES of each source (as ``fbi.models.metrics``): mean log loss and multi-class Brier with their 95 % interval (whole days
resampled, ``block_bootstrap_ci``), and the Brier split as Murphy did (``murphy``): reliability (how far the stated probabilities are
from the frequencies seen; lower is better), resolution (how far the frequencies seen in each bin are from the overall one; higher is
better) and uncertainty (that of the outcomes themselves), each category of the market as a binary event in ten equal bins and summed;
``Brier = reliability - resolution + uncertainty + residual``, the residual being what the bins cannot see (exactly 0 when every forecast
in a bin is the same). Reliability and resolution carry their interval too (500 resamplings of whole days).

THE PAIRS (``pairs``): model against market and model against provider, the paired difference per match of the log loss and of the
Brier (negative: the model scored better), with its interval and a word: ``modelo_mejor`` (the whole interval below 0), ``modelo_peor``
(above), ``indistinguible``, or ``insuficiente`` below ``MIN_PAIRED`` matches or on one day.

It is NOT a proof of an edge: a better score on a few hundred matches is a reading, and a better log loss than the market is not a
profit. Reads only; ``store`` appends the report to ``analytics.evaluation_reports`` (``kind = 'weekly'``) and nothing else.
"""

from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Final

import numpy as np
import psycopg
from numpy.typing import NDArray
from psycopg.rows import dict_row
from psycopg.types.json import Json

from fbi.core.calendar import local_day
from fbi.coverage import model_segments as segments
from fbi.models.metrics import EPS, block_bootstrap_ci

VERSION: Final = "weekly-board-v1"
SWITCH: Final = "FBI_EVALUATION_BOARD"
JOB: Final = "evaluation_board"
BINS: Final = 10
MIN_PAIRED: Final = 30
DECOMPOSITION_DRAWS: Final = 500
SEED: Final = 13
SOURCES: Final = ("modelo", "mercado", "proveedor")
NOTICE: Final = ("Tablero privado: no es una prueba de ventaja. Una puntuación mejor que la del mercado en unos cientos de partidos es "
                 "una lectura, no un beneficio; nada de esto cambia picks, modelos ni probabilidades.")


def mode(env: Mapping[str, str] | None = None) -> str:
    """``off`` unless the switch says on: the weekly batch computes the board, and the owner's route shows it, only then."""
    e = os.environ if env is None else env
    return "on" if e.get(SWITCH, "0").strip().lower() in ("1", "on", "true", "yes") else "off"


# ── pure ───────────────────────────────────────────────────────────────────────────────────────────────────────────────


def murphy(p: NDArray[np.float64], y: NDArray[np.int64], bins: int = BINS) -> dict[str, float]:
    """Murphy's split of the multi-class Brier score of forecasts ``p`` (n x k) for outcomes ``y``: each category a binary event in
    ``bins`` equal-width bins, summed over the categories. ``brier = reliability - resolution + uncertainty + residual``."""
    n, k = p.shape
    onehot = np.eye(k)[y]
    rel = res = unc = 0.0
    for c in range(k):
        q, o = p[:, c], onehot[:, c]
        base = float(o.mean())
        unc += base * (1 - base)
        idx = np.minimum((q * bins).astype(int), bins - 1)
        for b in range(bins):
            mask = idx == b
            m = int(mask.sum())
            if not m:
                continue
            qb, ob = float(q[mask].mean()), float(o[mask].mean())
            rel += m * (qb - ob) ** 2 / n
            res += m * (ob - base) ** 2 / n
    brier = float(((p - onehot) ** 2).sum(axis=1).mean())
    return {"brier": brier, "reliability": rel, "resolution": res, "uncertainty": unc, "residual": brier - (rel - res + unc)}


def _days_bootstrap(p: NDArray[np.float64], y: NDArray[np.int64], days: Sequence[date], *, draws: int, seed: int
                    ) -> tuple[tuple[float, float] | None, tuple[float, float] | None]:
    groups: dict[date, list[int]] = defaultdict(list)
    for i, d in enumerate(days):
        groups[d].append(i)
    keys = sorted(groups)
    if len(keys) < 2:
        return None, None
    rng = np.random.default_rng(seed)
    rels, ress = [], []
    for _ in range(draws):
        pick = rng.integers(0, len(keys), size=len(keys))
        idx = np.concatenate([np.asarray(groups[keys[j]]) for j in pick])
        m = murphy(p[idx], y[idx])
        rels.append(m["reliability"])
        ress.append(m["resolution"])
    return ((float(np.quantile(rels, 0.025)), float(np.quantile(rels, 0.975))),
            (float(np.quantile(ress, 0.025)), float(np.quantile(ress, 0.975))))


def _r(x: float | None) -> float | None:
    return None if x is None else round(x, 6)


def _iv(value: float, low: float | None, high: float | None) -> dict[str, float | None]:
    return {"value": _r(value), "low": _r(low), "high": _r(high)}


def _per_match(p: NDArray[np.float64], y: NDArray[np.int64]) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    ll = -np.log(np.clip(p[np.arange(len(y)), y], EPS, 1.0))
    br = ((p - np.eye(p.shape[1])[y]) ** 2).sum(axis=1)
    return ll, br


def score(name: str, p: NDArray[np.float64], y: NDArray[np.int64], days: Sequence[date], *, seed: int = SEED,
          draws: int = DECOMPOSITION_DRAWS) -> dict[str, Any]:
    """Every measure of one source on ``len(y)`` matches."""
    ll, br = _per_match(p, y)
    many = len(set(days)) >= 2
    _, ll_lo, ll_hi, _ = block_bootstrap_ci(ll, days, seed=seed) if many else (0.0, None, None, 0)
    _, br_lo, br_hi, _ = block_bootstrap_ci(br, days, seed=seed + 1) if many else (0.0, None, None, 0)
    m = murphy(p, y)
    rel_ci, res_ci = _days_bootstrap(p, y, days, draws=draws, seed=seed + 2)
    return {"source": name, "n": len(y), "days": len(set(days)),
            "log_loss": _iv(float(ll.mean()), ll_lo, ll_hi), "brier": _iv(m["brier"], br_lo, br_hi),
            "reliability": _iv(m["reliability"], *(rel_ci or (None, None))),
            "resolution": _iv(m["resolution"], *(res_ci or (None, None))),
            "uncertainty": round(m["uncertainty"], 6), "residual": round(m["residual"], 6)}


def paired(a: str, b: str, pa: NDArray[np.float64], pb: NDArray[np.float64], y: NDArray[np.int64], days: Sequence[date], *,
           seed: int = SEED) -> list[dict[str, Any]]:
    """The paired differences (a minus b) of the log loss and the Brier on the same matches, with the word they allow."""
    la, ba = _per_match(pa, y)
    lb, bb = _per_match(pb, y)
    out = []
    for metric, d in (("log_loss", la - lb), ("brier", ba - bb)):
        n = len(d)
        if n < MIN_PAIRED or len(set(days)) < 2:
            out.append({"a": a, "b": b, "metric": metric, "n": n, **_iv(float(d.mean()) if n else 0.0, None, None),
                        "verdict": "insuficiente"})
            continue
        mean, lo, hi, _ = block_bootstrap_ci(d, days, seed=seed + 3)
        word = "modelo_mejor" if hi < 0 else "modelo_peor" if lo > 0 else "indistinguible"
        out.append({"a": a, "b": b, "metric": metric, "n": n, **_iv(mean, lo, hi), "verdict": word})
    return out


@dataclass(frozen=True, slots=True)
class Match:
    fixture_id: int
    day: date
    y: int
    p: dict[str, tuple[float, ...]]
    """The probabilities of each source that has a whole set, in the order of ``segments.MARKETS``."""


def window(market: str, matches: Sequence[Match], *, start: date, end: date) -> dict[str, Any]:
    """The board of one market over the matches of ``[start, end]`` (Bogotá days): each source on the matches all the sources of the
    market share (the provider only in 1X2), and the pairs."""
    names = ("modelo", "mercado", "proveedor") if market == "1X2" else ("modelo", "mercado")
    inside = [m for m in matches if start <= m.day <= end]
    with_each = {s: sum(1 for m in inside if s in m.p) for s in names}
    common = [m for m in inside if all(s in m.p for s in names)]
    pair = [m for m in inside if "modelo" in m.p and "mercado" in m.p]
    out: dict[str, Any] = {"from": start.isoformat(), "to": end.isoformat(), "matches": len(inside), "with_each": with_each,
                           "common": len(common), "sources": [], "pairs": []}
    if common:
        y = np.array([m.y for m in common], dtype=np.int64)
        days = [m.day for m in common]
        for s in names:
            out["sources"].append(score(s, np.array([m.p[s] for m in common]), y, days))
    if pair:
        y = np.array([m.y for m in pair], dtype=np.int64)
        days = [m.day for m in pair]
        out["pairs"] += paired("modelo", "mercado", np.array([m.p["modelo"] for m in pair]), np.array([m.p["mercado"] for m in pair]),
                               y, days)
    if market == "1X2":
        trio = [m for m in inside if "modelo" in m.p and "proveedor" in m.p]
        if trio:
            y = np.array([m.y for m in trio], dtype=np.int64)
            out["pairs"] += paired("modelo", "proveedor", np.array([m.p["modelo"] for m in trio]),
                                   np.array([m.p["proveedor"] for m in trio]), y, [m.day for m in trio])
    return out


def last_week(at: datetime) -> tuple[date, date]:
    """The last whole week (Monday to Sunday, Bogotá) before the day of ``at``."""
    today = local_day(at)
    monday = today - timedelta(days=today.weekday() + 7)
    return monday, monday + timedelta(days=6)


# ── the database ───────────────────────────────────────────────────────────────────────────────────────────────────────

MARKET_SQL: Final = """
WITH f AS (
    SELECT f.id, f.kickoff_at FROM core.fixtures f JOIN core.fixture_results r ON r.fixture_id = f.id
     WHERE f.id = ANY(%(ids)s)
), last AS (
    SELECT c.fixture_id, c.market_key, c.line, max(c.as_of) AS k
      FROM market.market_consensus c JOIN f ON f.id = c.fixture_id
     WHERE c.devig_method = 'shin' AND c.as_of < f.kickoff_at AND c.as_of <= %(at)s
       AND ((c.market_key = '1X2' AND c.line = 0) OR (c.market_key = 'OU' AND c.line = 2.5) OR (c.market_key = 'BTTS' AND c.line = 0))
     GROUP BY 1, 2, 3
)
SELECT c.fixture_id, c.market_key, c.selection, c.p_fair
  FROM last l JOIN market.market_consensus c
    ON c.fixture_id = l.fixture_id AND c.market_key = l.market_key AND c.line = l.line AND c.as_of = l.k AND c.devig_method = 'shin'
 WHERE c.p_fair IS NOT NULL
"""
PROVIDER_SQL: Final = """
SELECT DISTINCT ON (p.fixture_id) p.fixture_id, p.percent_home, p.percent_draw, p.percent_away
  FROM core.provider_predictions p JOIN core.fixtures f ON f.id = p.fixture_id
 WHERE p.fixture_id = ANY(%(ids)s) AND p.observed_at < f.kickoff_at AND p.observed_at <= %(at)s
 ORDER BY p.fixture_id, p.observed_at DESC
"""


def provider_set(home: Any, draw: Any, away: Any) -> tuple[float, float, float] | None:
    """The provider's three percents over their sum; None when one is missing or they add up to nothing."""
    if home is None or draw is None or away is None:
        return None
    h, d, a = float(home), float(draw), float(away)
    total = h + d + a
    return None if total <= 0 else (h / total, d / total, a / total)


def matches(conn: psycopg.Connection[Any], *, at: datetime, start: date, end: date) -> dict[str, list[Match]]:
    """Every market's matches of ``[start, end]`` with the model's forecast and whichever other sources have a whole set."""
    found, _ = segments.load(conn, source="forecast", at=at, start=start, end=end + timedelta(days=1))
    by_market: dict[str, dict[int, Match]] = defaultdict(dict)
    for s in found:
        by_market[s.market][s.fixture_id] = Match(s.fixture_id, s.day, s.y, {"modelo": s.p})
    ids = sorted({s.fixture_id for s in found})
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(MARKET_SQL, {"ids": ids, "at": at})
        sets: dict[tuple[int, str], dict[str, float]] = defaultdict(dict)
        for r in cur.fetchall():
            sets[(int(r["fixture_id"]), str(r["market_key"]))][str(r["selection"])] = float(r["p_fair"])
        for (fid, market), probs in sets.items():
            m = by_market.get(market, {}).get(fid)
            names = segments.MARKETS[market][1]
            if m is not None and set(probs) == set(names):
                m.p["mercado"] = tuple(probs[s] for s in names)
        cur.execute(PROVIDER_SQL, {"ids": ids, "at": at})
        for r in cur.fetchall():
            m = by_market.get("1X2", {}).get(int(r["fixture_id"]))
            got = provider_set(r["percent_home"], r["percent_draw"], r["percent_away"])
            if m is not None and got is not None:
                m.p["proveedor"] = got
    return {k: sorted(v.values(), key=lambda m: (m.day, m.fixture_id)) for k, v in by_market.items()}


def report(conn: psycopg.Connection[Any], *, at: datetime, week: tuple[date, date] | None = None) -> dict[str, Any]:
    """The board of the last whole week and of everything since ``segments.FIRST_DAY``, market by market."""
    monday, sunday = week or last_week(at)
    found = matches(conn, at=at, start=segments.FIRST_DAY, end=sunday)
    markets = []
    for market in segments.MARKETS:
        ms = found.get(market, [])
        markets.append({"market": market, "line": float(segments.MARKETS[market][0]),
                        "week": window(market, ms, start=monday, end=sunday),
                        "cumulative": window(market, ms, start=segments.FIRST_DAY, end=sunday)})
    return {"version": VERSION, "at": at.isoformat(), "period_from": monday.isoformat(), "period_to": sunday.isoformat(),
            "cumulative_from": segments.FIRST_DAY.isoformat(), "bins": BINS, "min_paired": MIN_PAIRED, "markets": markets,
            "notice_es": NOTICE}


INSERT_SQL: Final = """
INSERT INTO analytics.evaluation_reports (kind, version, period_from, period_to, computed_at, code_version, body)
VALUES ('weekly', %(version)s, %(start)s, %(end)s, %(at)s, %(code)s, %(body)s)
ON CONFLICT (kind, version, period_to) DO NOTHING RETURNING id
"""


def store(conn: psycopg.Connection[Any], rep: Mapping[str, Any], *, code_version: str) -> int | None:
    """Appends the board (the caller commits). None when the board of that week is already stored."""
    row = conn.execute(INSERT_SQL, {"version": VERSION, "start": rep["period_from"], "end": rep["period_to"], "at": rep["at"],
                                    "code": code_version[:64] or "desconocido", "body": Json(dict(rep))}).fetchone()
    return None if row is None else int(row[0])
