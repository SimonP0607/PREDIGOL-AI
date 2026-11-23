"""The models judged by competition and by coverage level (plan PM, PM-12-06): ``segments-v1``. PRIVATE, and it decides nothing.

The calibration of PrediGol reads its backtest as a whole and never looks at the competition (H-EST-01); the leagues added lately have
little history of their own. This module scores the forecasts already stored against the results, split by competition and by the
summary level of the availability matrix, and says for each competition whether its OWN sample is enough to authorise a probability
there. Three sources, the same rules:

* ``forecast``   what a reader is shown: ``models.match_forecasts`` ``forecast-v1``, the newest set known before kick-off;
* ``prediction`` each model's own figure: ``models.predictions`` made in real time (no backtest session), the newest set before
                 kick-off of each model (its registry name, whatever its code version);
* ``backtest``   a LAB session: ``analytics.backtest_samples`` of its runs (the run's name and id, ``ensemble #57``, is the model).

Markets: ``1X2``; ``OU`` at 2.5; ``BTTS`` (``MARKETS``). The result is the 90-minute score (``reg_goals_*``, else ``ft_goals_*``: what
the walk-forward settles on). A match is scored only with every selection of the market present.

THE MEASURES of a segment (as ``fbi.models.metrics`` and the backtest compute them): mean log loss (``-ln max(p, 1e-15)`` of what
happened), multi-class Brier (``Σ (p_k - 1[k])²``), RPS for 1X2, each with the interval of ``block_bootstrap_ci`` (whole Bogotá days
resampled, 2.000 draws, 95 %). THE SKILL: the log loss minus that of the segment's own frequencies of the outcomes (climatology), per
match; negative is better.

THE VERDICT of a segment (``verdict``):

* ``insuficiente`` below ``NEEDED`` matches (the sample AD-K02 asks of a cell, ``fbi.evaluation.board.NEEDED``; a test keeps them equal):
  a number is not given as a judgement, «insuficiente» is;
* ``sin_habilidad`` with the sample, when the upper end of the skill's interval is not below zero (it does not beat its own frequencies);
* ``apta`` otherwise.

A competition with no row has no verdict at all: in the resolver (``fbi.coverage.resolve``, state 5, only with
``FBI_PROB_BY_COMPETITION``) it reads «no autorizada», so every new competition is born not authorised.

THE REPRODUCTION (``reproduction``): for every source, model and market, the matches and the n-weighted sum of the segments' log loss and
Brier give back the global figure, by competition and by level; and for a LAB session the global figures equal the ones the server stored
for each run (``analytics.backtest_runs``).

Reads predictions and results; ``store`` appends the report to ``analytics.evaluation_reports`` and ``analytics.evaluation_segments`` and
nothing else. Nothing that decides, prices or publishes imports this module; no pick, model, threshold or forecast changes.
"""

from __future__ import annotations

import math
import os
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final

import numpy as np
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from fbi.core.calendar import day_start, local_day
from fbi.coverage import levels
from fbi.models.metrics import EPS, block_bootstrap_ci, per_match_rps

VERSION: Final = "segments-v1"
SWITCH: Final = "FBI_MODEL_SEGMENTS"
JOB: Final = "model_segments"
NEEDED: Final = 300
"""As ``fbi.evaluation.board.NEEDED`` (AD-K02's sample of a cell; a test keeps them equal)."""
DRAWS: Final = 2000
SEED: Final = 11
MARKETS: Final[dict[str, tuple[Decimal, tuple[str, ...]]]] = {
    "1X2": (Decimal("0"), ("Home", "Draw", "Away")),
    "OU": (Decimal("2.5"), ("Over", "Under")),
    "BTTS": (Decimal("0"), ("Yes", "No")),
}
SOURCES: Final = ("forecast", "prediction", "backtest")
FORECAST_VERSION: Final = "forecast-v1"
FIRST_DAY: Final = date(2026, 10, 23)
"""The first Bogotá day with ``forecast-v1`` sets (the report is cumulative from it)."""
UNMEASURED: Final = "sin_medir"
VERDICTS: Final = ("apta", "sin_habilidad", "insuficiente")
NOTICE: Final = ("Evaluación privada: no cambia picks, modelos ni probabilidades. «Insuficiente» quiere decir que la competición no "
                 "tiene muestra propia; un «apta» no es una prueba de ventaja sobre el mercado.")


def mode(env: Mapping[str, str] | None = None) -> str:
    """``off`` unless the switch says on: the weekly batch computes and stores the report only then."""
    e = os.environ if env is None else env
    return "on" if e.get(SWITCH, "0").strip().lower() in ("1", "on", "true", "yes") else "off"


# ── pure ───────────────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Sample:
    """One scored match of one source, model and market."""

    source: str
    model: str
    market: str
    fixture_id: int
    competition_id: int
    level: str
    day: date
    p: tuple[float, ...]
    """In the order of ``MARKETS[market]``."""
    y: int
    """The index of what happened."""

    @property
    def log_loss(self) -> float:
        return -math.log(min(max(self.p[self.y], EPS), 1.0))

    @property
    def brier(self) -> float:
        return sum((q - (1.0 if k == self.y else 0.0)) ** 2 for k, q in enumerate(self.p))


def outcome(market: str, home: int, away: int) -> int:
    """The index of what happened in ``market`` with the 90-minute score."""
    if market == "1X2":
        return 0 if home > away else 1 if home == away else 2
    if market == "OU":
        return 0 if home + away > float(MARKETS["OU"][0]) else 1
    if market == "BTTS":
        return 0 if home > 0 and away > 0 else 1
    raise ValueError(f"market not evaluated: {market}")


def verdict(n: int, skill_high: float | None, needed: int = NEEDED) -> str:
    if n < needed:
        return "insuficiente"
    if skill_high is None or skill_high >= 0:
        return "sin_habilidad"
    return "apta"


def _r(x: float | None) -> float | None:
    return None if x is None else round(x, 6)


def group(items: Sequence[Sample], *, needed: int = NEEDED, seed: int = SEED) -> dict[str, Any]:
    """Every measure of one segment and its verdict."""
    n = len(items)
    k = len(items[0].p)
    days = [s.day for s in items]
    ll = np.array([s.log_loss for s in items])
    counts = Counter(s.y for s in items)
    freq = [counts.get(j, 0) / n for j in range(k)]
    clim = np.array([-math.log(max(freq[s.y], EPS)) for s in items])
    skill = ll - clim
    many = len(set(days)) >= 2
    _, ll_lo, ll_hi, _ = block_bootstrap_ci(ll, days, draws=DRAWS, seed=seed) if many else (0.0, None, None, 0)
    _, sk_lo, sk_hi, _ = block_bootstrap_ci(skill, days, draws=DRAWS, seed=seed + 1) if many else (0.0, None, None, 0)
    rps = None
    if k == 3:
        rps = float(per_match_rps(np.array([s.p for s in items]), np.array([s.y for s in items], dtype=np.int64)).mean())
    return {"n": n, "days": len(set(days)), "log_loss": _r(float(ll.mean())), "log_loss_low": _r(ll_lo), "log_loss_high": _r(ll_hi),
            "brier": _r(sum(s.brier for s in items) / n), "rps": _r(rps), "climatology": [round(f, 4) for f in freq],
            "skill": _r(float(skill.mean())), "skill_low": _r(sk_lo), "skill_high": _r(sk_hi),
            "verdict": verdict(n, sk_hi, needed), "_ll_sum": float(ll.sum()), "_brier_sum": sum(s.brier for s in items)}


def build(samples: Iterable[Sample], *, needed: int = NEEDED, seed: int = SEED) -> list[dict[str, Any]]:
    """The segments: for each (source, model, market) one ``global``, one per competition and one per level."""
    buckets: dict[tuple[str, str, str, str, str], list[Sample]] = defaultdict(list)
    for s in samples:
        for kind, key in (("global", "*"), ("competition", str(s.competition_id)), ("level", s.level)):
            buckets[(s.source, s.model, s.market, kind, key)].append(s)
    out = []
    for (source, model, market, kind, key), items in sorted(buckets.items()):
        out.append({"source": source, "model": model, "market": market, "line": float(MARKETS[market][0]), "kind": kind, "key": key,
                    **group(items, needed=needed, seed=seed)})
    return out


def reproduction(segments: Sequence[Mapping[str, Any]], *, tolerance: float = 1e-9) -> list[dict[str, Any]]:
    """For each (source, model, market) and each partition (competition, level): the segments add back to the global figure."""
    glob = {(s["source"], s["model"], s["market"]): s for s in segments if s["kind"] == "global"}
    out = []
    for key, g in sorted(glob.items()):
        for kind in ("competition", "level"):
            parts = [s for s in segments if (s["source"], s["model"], s["market"]) == key and s["kind"] == kind]
            n = sum(int(s["n"]) for s in parts)
            ll = sum(float(s["_ll_sum"]) for s in parts) / n if n else math.nan
            br = sum(float(s["_brier_sum"]) for s in parts) / n if n else math.nan
            g_ll, g_br = g["_ll_sum"] / g["n"], g["_brier_sum"] / g["n"]
            ok = n == g["n"] and abs(ll - g_ll) <= tolerance and abs(br - g_br) <= tolerance
            out.append({"source": key[0], "model": key[1], "market": key[2], "partition": kind, "segments": len(parts), "n": n,
                        "global_n": g["n"], "log_loss": round(ll, 9), "global_log_loss": round(g_ll, 9), "brier": round(br, 9),
                        "global_brier": round(g_br, 9), "reproduced": ok})
    return out


def public(segment: Mapping[str, Any]) -> dict[str, Any]:
    """A segment without its internal sums."""
    return {k: v for k, v in segment.items() if not k.startswith("_")}


def by_competition(segments: Iterable[Mapping[str, Any]], *, source: str = "forecast") -> dict[str, dict[str, str]]:
    """``{competition_id: {market: verdict}}`` of one source: a market is ``apta`` in a competition when one of its models is."""
    out: dict[str, dict[str, str]] = defaultdict(dict)
    rank = {"apta": 2, "sin_habilidad": 1, "insuficiente": 0}
    for s in segments:
        if s["source"] != source or s["kind"] != "competition":
            continue
        now = out[s["key"]].get(s["market"])
        if now is None or rank[s["verdict"]] > rank[now]:
            out[s["key"]][s["market"]] = s["verdict"]
    return dict(out)


def samples_of(rows: Iterable[Mapping[str, Any]], *, source: str, levels_of: Mapping[int, str]) -> tuple[list[Sample], int]:
    """Samples from rows of one selection each (``fixture_id``, ``model``, ``market_key``, ``selection``, ``p``, ``goals_home``,
    ``goals_away``, ``kickoff_at``, ``competition_id``, ``competition_season_id``): a match with a selection missing is left out and
    counted."""
    sets: dict[tuple[int, str, str], dict[str, Any]] = {}
    for r in rows:
        key = (int(r["fixture_id"]), str(r["model"]), str(r["market_key"]))
        found = sets.setdefault(key, {"row": r, "p": {}})
        found["p"][str(r["selection"])] = float(r["p"])
    out, incomplete = [], 0
    for (fixture, model, market), found in sorted(sets.items()):
        names = MARKETS[market][1]
        if set(found["p"]) != set(names):
            incomplete += 1
            continue
        r = found["row"]
        out.append(Sample(source=source, model=model, market=market, fixture_id=fixture, competition_id=int(r["competition_id"]),
                          level=levels_of.get(int(r["competition_season_id"]), UNMEASURED), day=local_day(r["kickoff_at"]),
                          p=tuple(found["p"][s] for s in names), y=outcome(market, int(r["goals_home"]), int(r["goals_away"]))))
    return out, incomplete


# ── the database ───────────────────────────────────────────────────────────────────────────────────────────────────────

_MARKET_FILTER: Final = "((x.market_key = '1X2' AND x.line = 0) OR (x.market_key = 'OU' AND x.line = 2.5) OR (x.market_key = 'BTTS' AND x.line = 0))"
_RESULT: Final = """
  JOIN core.fixtures f ON f.id = x.fixture_id
  JOIN core.fixture_results r ON r.fixture_id = f.id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
"""
_RESULT_COLUMNS: Final = ("coalesce(r.reg_goals_home, r.ft_goals_home) AS goals_home, coalesce(r.reg_goals_away, r.ft_goals_away) "
                          "AS goals_away, f.kickoff_at, cs.competition_id, f.competition_season_id")
_WINDOW: Final = ("f.kickoff_at >= %(start)s AND f.kickoff_at < %(end)s AND r.settled_at <= %(at)s "
                  "AND coalesce(r.reg_goals_home, r.ft_goals_home) IS NOT NULL")

FORECAST_SQL: Final = f"""
WITH last AS (
    SELECT x.fixture_id, x.market_key, x.line, max(x.known_at) AS k
      FROM models.match_forecasts x {_RESULT}
     WHERE x.version = %(version)s AND x.known_at < f.kickoff_at AND x.known_at <= %(at)s AND {_MARKET_FILTER} AND {_WINDOW}
     GROUP BY 1, 2, 3
)
SELECT x.fixture_id, x.model_name AS model, x.market_key, x.selection, x.p, {_RESULT_COLUMNS}
  FROM last l JOIN models.match_forecasts x
    ON x.fixture_id = l.fixture_id AND x.version = %(version)s AND x.market_key = l.market_key AND x.line = l.line AND x.known_at = l.k
  {_RESULT}
"""

PREDICTION_SQL: Final = f"""
WITH cand AS (
    SELECT x.fixture_id, g.name, x.market_key, x.line, x.model_version_id, x.data_cutoff_ts
      FROM models.predictions x
      JOIN models.model_versions v ON v.id = x.model_version_id JOIN models.model_registry g ON g.id = v.model_id
      {_RESULT}
     WHERE x.backtest_session_id IS NULL AND x.data_cutoff_ts < f.kickoff_at AND x.created_at <= %(at)s AND {_MARKET_FILTER}
       AND {_WINDOW}
), last AS (
    SELECT DISTINCT ON (fixture_id, name, market_key, line) fixture_id, name, market_key, line, model_version_id, data_cutoff_ts
      FROM cand ORDER BY fixture_id, name, market_key, line, data_cutoff_ts DESC, model_version_id DESC
)
SELECT x.fixture_id, l.name AS model, x.market_key, x.selection, x.p_calibrated AS p, {_RESULT_COLUMNS}
  FROM last l JOIN models.predictions x
    ON x.fixture_id = l.fixture_id AND x.model_version_id = l.model_version_id AND x.market_key = l.market_key AND x.line = l.line
   AND x.data_cutoff_ts = l.data_cutoff_ts AND x.backtest_session_id IS NULL
  {_RESULT}
"""

BACKTEST_SQL: Final = f"""
SELECT x.fixture_id, b.name || ' #' || b.id AS model, x.market_key, x.selection, x.p_calibrated AS p, {_RESULT_COLUMNS}
  FROM analytics.backtest_samples x JOIN analytics.backtest_runs b ON b.id = x.backtest_run_id
  {_RESULT}
 WHERE b.session_id = %(session)s AND {_MARKET_FILTER}
"""

STORED_RUNS_SQL: Final = "SELECT name || ' #' || id AS name, n_samples, logloss, brier_score FROM analytics.backtest_runs WHERE session_id = %(session)s"

LEVELS_SQL: Final = """
SELECT competition_season_id, 'd' AS kind, datum AS key, level FROM analytics.coverage_cells
 WHERE phase_key = 'todas' AND competition_season_id = ANY(%(cs)s)
UNION ALL
SELECT competition_season_id, 'm', market_key, level FROM analytics.market_availability WHERE competition_season_id = ANY(%(cs)s)
"""


def season_levels(conn: psycopg.Connection[Any], seasons: Sequence[int]) -> dict[int, str]:
    """The matrix's summary label of each competition season (``levels.summary_level``; ``sin_medir`` without cells)."""
    data: dict[int, dict[str, levels.Level]] = defaultdict(dict)
    markets: dict[int, dict[str, levels.Level]] = defaultdict(dict)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(LEVELS_SQL, {"cs": list(seasons)})
        for r in cur.fetchall():
            (data if r["kind"] == "d" else markets)[int(r["competition_season_id"])][str(r["key"])] = r["level"]
    out = {}
    for cs in data:
        d = {k: data[cs].get(k, "MI") for k in levels.DATA}
        m = {k: markets[cs].get(k, "MI") for k in levels.MARKETS}
        out[cs] = levels.summary_level(d, m).label
    return out


def _fetch(conn: psycopg.Connection[Any], sql: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def load(conn: psycopg.Connection[Any], *, source: str, at: datetime, start: date = FIRST_DAY, end: date | None = None,
         session: int | None = None) -> tuple[list[Sample], int]:
    """The samples of one source and how many matches lacked a selection. ``start``/``end``: Bogotá days of kick-off (``end``
    excluded; by default the day of ``at``); a backtest reads its ``session`` whole."""
    if source == "backtest":
        if session is None:
            raise ValueError("a backtest source needs its session")
        rows = _fetch(conn, BACKTEST_SQL, {"session": session})
    else:
        stop = local_day(at) if end is None else end
        params = {"start": day_start(start), "end": day_start(stop), "at": at, "version": FORECAST_VERSION}
        rows = _fetch(conn, FORECAST_SQL if source == "forecast" else PREDICTION_SQL, params)
    lv = season_levels(conn, sorted({int(r["competition_season_id"]) for r in rows}))
    return samples_of(rows, source=source, levels_of=lv)


def stored_runs(conn: psycopg.Connection[Any], session: int) -> dict[str, dict[str, Any]]:
    return {str(r["name"]): r for r in _fetch(conn, STORED_RUNS_SQL, {"session": session})}


def backtest_reproduction(segments: Sequence[Mapping[str, Any]], stored: Mapping[str, Mapping[str, Any]], *,
                          tolerance: float = 2e-5) -> list[dict[str, Any]]:
    """The global 1X2 figures of each run of a LAB session against the ones the server stored (``scripts.lab_reproduce``'s
    tolerance: the probabilities were stored rounded to 6 decimals)."""
    out = []
    for s in segments:
        if s["source"] != "backtest" or s["kind"] != "global" or s["market"] != "1X2":
            continue
        run = stored.get(s["model"])
        if run is None or run["logloss"] is None:
            out.append({"model": s["model"], "n": s["n"], "reproduced": None})
            continue
        ll, br = s["_ll_sum"] / s["n"], s["_brier_sum"] / s["n"]
        ok = (int(run["n_samples"]) == s["n"] and abs(ll - float(run["logloss"])) <= tolerance
              and abs(br - float(run["brier_score"])) <= tolerance)
        out.append({"model": s["model"], "n": s["n"], "stored_n": int(run["n_samples"]), "log_loss": round(ll, 6),
                    "stored_log_loss": float(run["logloss"]), "brier": round(br, 6), "stored_brier": float(run["brier_score"]),
                    "reproduced": ok})
    return out


def report(conn: psycopg.Connection[Any], *, at: datetime, start: date = FIRST_DAY, sources: Sequence[str] = ("forecast", "prediction"),
           session: int | None = None) -> dict[str, Any]:
    """The whole report: segments of every source asked, the reproduction checks, and the verdicts by competition (forecast)."""
    segments: list[dict[str, Any]] = []
    incomplete: dict[str, int] = {}
    for source in sources:
        found, missing = load(conn, source=source, at=at, start=start, session=session)
        segments.extend(build(found))
        incomplete[source] = missing
    repro = reproduction(segments)
    out: dict[str, Any] = {"version": VERSION, "at": at.isoformat(), "period_from": start.isoformat(),
                           "period_to": local_day(at).isoformat(), "needed": NEEDED, "sources": list(sources), "session": session,
                           "incomplete": incomplete, "reproduction": repro, "reproduced": all(r["reproduced"] for r in repro),
                           "notice_es": NOTICE}
    if session is not None and "backtest" in sources:
        out["backtest_reproduction"] = backtest_reproduction(segments, stored_runs(conn, session))
    counts = Counter((s["source"], s["kind"], s["verdict"]) for s in segments)
    out["counts"] = [{"source": a, "kind": b, "verdict": c, "segments": n} for (a, b, c), n in sorted(counts.items())]
    out["segments"] = segments
    return out


INSERT_REPORT: Final = """
INSERT INTO analytics.evaluation_reports (kind, version, period_from, period_to, computed_at, code_version, body)
VALUES ('segments', %(version)s, %(start)s, %(end)s, %(at)s, %(code)s, %(body)s)
ON CONFLICT (kind, version, period_to) DO NOTHING RETURNING id
"""
INSERT_SEGMENT: Final = """
INSERT INTO analytics.evaluation_segments (report_id, source, model_name, market_key, line, segment_kind, segment_key, n, days, log_loss,
    log_loss_low, log_loss_high, brier, rps, skill, skill_low, skill_high, verdict)
VALUES (%(report)s, %(source)s, %(model)s, %(market)s, %(line)s, %(kind)s, %(key)s, %(n)s, %(days)s, %(log_loss)s, %(log_loss_low)s,
    %(log_loss_high)s, %(brier)s, %(rps)s, %(skill)s, %(skill_low)s, %(skill_high)s, %(verdict)s)
"""


def store(conn: psycopg.Connection[Any], rep: Mapping[str, Any], *, code_version: str) -> int | None:
    """Appends the report and its segments (one transaction, the caller commits). None when this day's report already exists."""
    body = {k: v for k, v in rep.items() if k != "segments"}
    body["segments"] = len(rep["segments"])
    with conn.cursor() as cur:
        cur.execute(INSERT_REPORT, {"version": VERSION, "start": rep["period_from"], "end": rep["period_to"], "at": rep["at"],
                                    "code": code_version[:64] or "desconocido", "body": Json(body)})
        row = cur.fetchone()
        if row is None:
            return None
        report_id = int(row[0])
        cur.executemany(INSERT_SEGMENT, [{"report": report_id, **public(s), "key": str(s["key"])[:40]} for s in rep["segments"]])
    return report_id


LATEST_SQL: Final = """
SELECT s.market_key, s.verdict FROM analytics.evaluation_segments s
 WHERE s.segment_kind = 'competition' AND s.segment_key = %(key)s AND s.source = 'forecast'
   AND s.report_id = (SELECT max(id) FROM analytics.evaluation_reports WHERE kind = 'segments')
"""
"""The verdicts of one competition in the newest report (``fbi.coverage.resolve`` reads the same with its own statement)."""
