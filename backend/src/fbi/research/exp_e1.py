"""EXP-E1 of the plan (RP-9.1): in which segments, if any, does the raw model, which does not read the market, stand within +0.005 of the real close?

The protocol is ``fbi.research.exp_protocol.E1`` (registered and fingerprinted on 2026-11-26, before this module could produce a number). This module only
COUNTS the sample and RUNS the comparison; the thresholds, the interval by days, the Holm correction and the verdict are the ones of ``exp_protocol``.

What it reads (nothing else, 0 provider requests, 0 AI):

* the 1X2 forecast of each simple model that reads no market (``MODELS``), the newest one stored BEFORE kick-off (``models.predictions.p_raw``: the raw figure,
  not the calibrated one);
* the consensus of the real close (``market.near_close_consensus``, RP-1.4: the last price of each bookmaker in the last hour, de-vigged with Shin, at
  least two books);
* the 90-minute result of a match the historical validation did not quarantine;
* only matches that kicked off AFTER the day the protocol was signed. The matches already looked at (23 Oct to 25 Nov) only validate.

The primary figure is the equal-weight logarithmic pool of the models that predicted the match (at least two: no fitting of its own, so nothing to leak),
the same as the ensemble of the research (``v2_models.ensemble_run``); each model on its own is a secondary figure on the same matches. A match belongs to
the segments of its tier (``nivel 1`` to ``nivel 5``) and of its kind (national leagues, national cups, national-team competitions): it can be in two.
The sample of the experiment is the number of matches of its FULLEST segment; the verdict is for the segments that have the fixed 1,000: a success if any of
them stands within the threshold (with Holm over the segments judged and the same sign in both halves), an abandonment only when EVERY one of the eight
segments has its sample and none comes below the threshold, and otherwise «insufficient» (the experiment goes on, and no segment is added or dropped).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final

import numpy as np
import psycopg
from psycopg.rows import dict_row

from fbi.research import exp_conditions, exp_protocol
from fbi.research.exp_protocol import Judgement

KEY: Final = "EXP-E1"
MODELS: Final = ("poisson", "dixon_coles", "elo_ologit", "mnlogit")
"""The simple models that read no market (the ones the production pipeline stores a raw figure for are a subset of them today)."""
MIN_MODELS: Final = 2
SEGMENTS: Final = exp_protocol.E1.segments
CLIP: Final = 1e-12

ROWS_SQL: Final = """
WITH played AS (
    SELECT f.id, f.kickoff_at, r.reg_goals_home AS h, r.reg_goals_away AS a, c.competition_type, c.entity_scope, c.tier
      FROM core.fixtures f
      JOIN core.fixture_results r ON r.fixture_id = f.id
      JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
      JOIN core.competitions c ON c.id = cs.competition_id
     WHERE f.status_group = 'finished' AND f.kickoff_at >= %(after)s AND f.kickoff_at < %(until)s
       AND r.reg_goals_home IS NOT NULL AND r.reg_goals_away IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM analytics.fixture_validation v WHERE v.fixture_id = f.id AND v.state IN ('QUARANTINED', 'INGESTED'))
), forecast AS (
    SELECT DISTINCT ON (p.fixture_id, m.name) p.fixture_id, m.name AS model, p.model_version_id, p.data_cutoff_ts
      FROM models.predictions p
      JOIN played ON played.id = p.fixture_id
      JOIN models.model_versions v ON v.id = p.model_version_id
      JOIN models.model_registry m ON m.id = v.model_id
     WHERE p.backtest_session_id IS NULL AND p.market_key = '1X2' AND m.name = ANY(%(models)s)
       AND p.data_cutoff_ts < played.kickoff_at AND p.created_at < played.kickoff_at
     ORDER BY p.fixture_id, m.name, p.data_cutoff_ts DESC
), raw AS (
    SELECT fc.fixture_id, fc.model,
           max(p.p_raw) FILTER (WHERE p.selection = 'Home') AS ph,
           max(p.p_raw) FILTER (WHERE p.selection = 'Draw') AS pd,
           max(p.p_raw) FILTER (WHERE p.selection = 'Away') AS pa
      FROM forecast fc
      JOIN models.predictions p ON p.fixture_id = fc.fixture_id AND p.model_version_id = fc.model_version_id
                               AND p.data_cutoff_ts = fc.data_cutoff_ts AND p.market_key = '1X2' AND p.backtest_session_id IS NULL
     GROUP BY fc.fixture_id, fc.model
), close AS (
    SELECT n.fixture_id,
           max(n.p_fair) FILTER (WHERE n.selection = 'Home') AS qh,
           max(n.p_fair) FILTER (WHERE n.selection = 'Draw') AS qd,
           max(n.p_fair) FILTER (WHERE n.selection = 'Away') AS qa,
           min(n.n_bookmakers) AS books
      FROM market.near_close_consensus n JOIN played ON played.id = n.fixture_id
     WHERE n.market_key = '1X2' AND n.devig_method = 'shin' AND n.line = 0
     GROUP BY n.fixture_id
)
SELECT played.id, played.kickoff_at, played.h, played.a, played.competition_type, played.entity_scope, played.tier,
       raw.model, raw.ph, raw.pd, raw.pa, close.qh, close.qd, close.qa, close.books
  FROM played
  JOIN close ON close.fixture_id = played.id AND close.books >= 2
  JOIN raw ON raw.fixture_id = played.id
 ORDER BY played.kickoff_at, played.id
"""
"""One row per match and model that predicted it: the raw forecast, the real close (two books or more), the score and the competition."""


@dataclass(frozen=True, slots=True)
class Match:
    """A match of the experiment: who it is, the segments it belongs to, what happened, the close and the forecast of each model."""

    fixture: int
    day: date
    segments: tuple[str, ...]
    outcome: int
    close: tuple[float, float, float]
    forecasts: Mapping[str, tuple[float, float, float]]


def segments_of(*, tier: int | None, competition_type: str, entity_scope: str) -> tuple[str, ...]:
    """The segments of the protocol a competition is in (by its tier and by its kind), in the order of the protocol."""
    mine = set()
    if tier is not None and 1 <= tier <= 5:
        mine.add(f"nivel {tier}")
    if entity_scope == "national_team":
        mine.add("competiciones de selecciones")
    elif competition_type == "domestic_league":
        mine.add("ligas nacionales")
    elif competition_type == "domestic_cup":
        mine.add("copas nacionales")
    return tuple(s for s in SEGMENTS if s in mine)


def _triplet(a: Any, b: Any, c: Any) -> tuple[float, float, float] | None:
    if a is None or b is None or c is None:
        return None
    x = np.array([float(a), float(b), float(c)])
    total = float(x.sum())
    if total <= 0:
        return None
    x = x / total
    return float(x[0]), float(x[1]), float(x[2])


def pool(forecasts: Sequence[tuple[float, float, float]]) -> tuple[float, float, float]:
    """The equal-weight logarithmic pool of the forecasts (as the ensemble of the research makes it), renormalised."""
    logs = np.mean([np.log(np.clip(np.array(p), CLIP, 1.0)) for p in forecasts], axis=0)
    q = np.exp(logs)
    q /= q.sum()
    return float(q[0]), float(q[1]), float(q[2])


def log_loss(p: tuple[float, float, float], outcome: int) -> float:
    return float(-np.log(max(p[outcome], CLIP)))


def load(conn: psycopg.Connection[Any], *, after: datetime, until: datetime) -> list[Match]:
    """The matches that kicked off in ``[after, until)`` with at least ``MIN_MODELS`` raw forecasts and a real close. Reads only."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(ROWS_SQL, {"after": after, "until": until, "models": list(MODELS)})
        rows = cur.fetchall()
    per: dict[int, dict[str, Any]] = {}
    for r in rows:
        close = _triplet(r["qh"], r["qd"], r["qa"])
        p = _triplet(r["ph"], r["pd"], r["pa"])
        if close is None or p is None:
            continue
        entry = per.setdefault(int(r["id"]), {"at": r["kickoff_at"], "outcome": 0 if r["h"] > r["a"] else 1 if r["h"] == r["a"] else 2, "close": close,
                                              "segments": segments_of(tier=None if r["tier"] is None else int(r["tier"]),
                                                                      competition_type=str(r["competition_type"]), entity_scope=str(r["entity_scope"])),
                                              "forecasts": {}})
        entry["forecasts"][str(r["model"])] = p
    return [Match(fid, e["at"].date(), e["segments"], e["outcome"], e["close"], e["forecasts"])
            for fid, e in per.items() if len(e["forecasts"]) >= MIN_MODELS and e["segments"]]


def after_signature(since: date) -> datetime:
    """The first moment that counts: the day after the signature (a match of the day itself was looked at while the protocol was being written)."""
    return datetime.combine(since + timedelta(days=1), datetime.min.time(), tzinfo=UTC)


def by_segment(matches: Sequence[Match]) -> dict[str, list[Match]]:
    out: dict[str, list[Match]] = {s: [] for s in SEGMENTS}
    for m in matches:
        for s in m.segments:
            out[s].append(m)
    return out


def count(conn: psycopg.Connection[Any], since: date) -> int:
    """The sample of the experiment: the matches of its fullest segment, counted from the day after the signature."""
    far = datetime(2100, 1, 1, tzinfo=UTC)
    return max((len(v) for v in by_segment(load(conn, after=after_signature(since), until=far)).values()), default=0)


def differences(matches: Sequence[Match]) -> tuple[list[float], list[date]]:
    """For each match the loss of the pool of the models minus the loss of the real close (negative: the model read the match better)."""
    values = [log_loss(pool(list(m.forecasts.values())), m.outcome) - log_loss(m.close, m.outcome) for m in matches]
    return values, [m.day for m in matches]


def judge(matches: Sequence[Match], *, required: int, thresholds: Mapping[str, Any], seed: int) -> tuple[Judgement, dict[str, Any]]:
    """The verdict of the experiment on its matches, and the population it was judged on (every segment with its figures)."""
    success_below = float(thresholds["success_below"])
    groups = by_segment(matches)
    ready = {s: v for s, v in groups.items() if len(v) >= required}
    p_values: dict[str, float] = {}
    series: dict[str, tuple[list[float], list[date]]] = {}
    for s, ms in ready.items():
        values, days = differences(ms)
        series[s] = (values, days)
        p_values[s] = exp_protocol.one_sided_p(values, days, below=success_below, seed=seed)
    adjusted = exp_protocol.holm(p_values) if p_values else {}
    judged = {s: exp_protocol.difference_verdict(*series[s], success_below=success_below, n_required=required, seed=seed, adjusted_p=adjusted[s])
              for s in ready}
    segments: dict[str, Any] = {}
    for s, ms in groups.items():
        j = judged.get(s)
        segments[s] = {"matches": len(ms), "verdict": None if j is None else j.verdict,
                       "mean": None if j is None else j.mean, "low": None if j is None else j.low, "high": None if j is None else j.high,
                       "adjusted_p": None if j is None else j.adjusted_p}
    models: dict[str, Any] = {}
    for name in MODELS:
        own = [m for m in matches if name in m.forecasts]
        if own:
            vals = [log_loss(m.forecasts[name], m.outcome) - log_loss(m.close, m.outcome) for m in own]
            models[name] = {"matches": len(own), "mean": float(np.mean(vals))}
    population = {"segments": segments, "models": models, "matches": len({m.fixture for m in matches}), "primary": "pool of the raw models",
                  "comparator": "market.near_close_consensus (shin, 2 books or more)", "holm_over": sorted(ready)}
    wins = {s: j for s, j in judged.items() if j.verdict == "exito"}
    if wins:
        best = min(wins, key=lambda s: wins[s].mean)
        j = wins[best]
        return Judgement("exito", f"{best}: {j.reason}", j.mean, j.low, j.high, j.n, j.adjusted_p), population
    if len(judged) == len(SEGMENTS) and all(j.verdict == "abandono" for j in judged.values()):
        j = min(judged.values(), key=lambda x: x.mean)
        return Judgement("abandono", "ningún segmento baja de +0,005: el intervalo de cada uno queda por encima del umbral", j.mean, j.low, j.high, j.n,
                         j.adjusted_p), population
    if judged:
        j = min(judged.values(), key=lambda x: x.mean)
        return Judgement("insuficiente", "con la muestra fijada el intervalo aún admite las dos respuestas, o faltan segmentos con su muestra",
                         j.mean, j.low, j.high, j.n, j.adjusted_p), population
    top = max((len(v) for v in groups.values()), default=0)
    return Judgement("insuficiente", f"muestra {top} de {required}", float("nan"), float("nan"), float("nan"), top), population


def run(conn: psycopg.Connection[Any], at: datetime) -> tuple[Judgement, dict[str, Any]]:
    """The runner the launcher calls once the sample is there."""
    protocol = exp_protocol.EXPERIMENTS[KEY]
    matches = load(conn, after=after_signature(exp_conditions.SIGNED_ON), until=at)
    return judge(matches, required=int(exp_protocol.THRESHOLDS[KEY]["n_required"]), thresholds=exp_protocol.THRESHOLDS[KEY], seed=protocol.seed)


def register() -> exp_conditions.Spec:
    """Say how the experiment counts and runs (``scripts.exp_run`` calls it for each module of its ``PLUGINS``; importing the module registers nothing)."""
    return exp_conditions.register(KEY, count=count, run=run)


__all__ = ["KEY", "MODELS", "Match", "count", "judge", "load", "pool", "register", "run", "segments_of"]
