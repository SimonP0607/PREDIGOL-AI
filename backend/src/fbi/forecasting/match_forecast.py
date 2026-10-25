"""PrediGol's forecast of a match (plan F5, ``forecast-v1``): what it thinks will happen, kept apart from what is worth betting.

THREE THINGS THAT USED TO BE ONE. A **forecast** is a probability: "Over 2.5 goals: 58 %, give or take 5 points". A **value**
is a forecast set against a price: "at 2.10 that is +4 % expected value" - it needs a bookmaker, and it is the decision layer's
(``fbi.intel.decision``, ``intel.decisions``). A **pick** is a value that passed ten filters and was frozen
(``picks.picks``, the day's sets). Until this module only the last two existed: a candidate was born from a selection that had
already passed the value rule, so a match whose models were confident but whose price was short left no trace of the
confidence, and the product had nothing honest to say about it. Now every upcoming match that has a model gets its forecast,
whatever the price, and nothing in here can reach the other two: this module reads ``models.predictions``, the champion
calibrators and (only to calibrate) the market's de-vigged probability, and writes ``models.match_forecasts``. The decision
layer and the pick engine never read that table.

WHAT IS FORECAST. The core markets the goal models price from one score matrix and the Elo model prices for the result:
1X2, total goals at 2.5, both teams to score (``fbi.models.scoring.MARKET_ROWS``). Other families (goals by half, corners,
cards) join in F10 by adding rows here; the table is already keyed by family.

WHICH MODEL. Per market, the one the decision layer would use: the champion calibrator with the lowest out-of-sample log loss
among the models that priced it, else the best fit, else the first by name (``CalibrationState.primary_model``). All the
outcomes of a market come from that one model at one cut-off, so they add up to one.

CALIBRATED OR NOT. ``cal-logit2-v1`` found every model 10-15 points too confident on the selections it flags, which is why a
probability is only stated as calibrated where a CHAMPION calibrator exists for that (market, model) - today Over/Under only.
Everywhere else the model's own number is stated and marked UNCALIBRATED: PrediGol says so rather than dress it up. A champion
that uses the market's probability (``logit2``) needs a recent de-vigged consensus; without one the forecast is UNCALIBRATED
(``needs_price``), never calibrated against a stale price. The calibrator is applied to each outcome and the market is then
scaled to add up to one; the interval is the model's interval pushed through the same function. That is an approximation (the
calibrator was fitted on the selections the models flagged, not on every outcome) and ``models.match_forecasts`` keeps what is
needed to measure it once the results are in.

WHEN A ROW IS WRITTEN. When the market is new, when its model, version or calibrator changed, or when any outcome moved at
least ``MATERIAL_CHANGE`` (half a point): the table is a record of what PrediGol said and when, not a heartbeat. All outcomes
of a market are written together, so the newest ``known_at`` of a market is always a coherent set.

NOT FIT FOR A FORECAST. A match whose competition's data is not fit for models (``PRODUCT_ONLY``, ``INSUFFICIENT``) or that is
quarantined gets none - the same gate the decision layer applies before it looks at a model.

WHERE IT LIVES. In ``fbi.forecasting``, not in ``fbi.predictions``: the latter is one of the packages whose code IS the models' code
(``fbi.core.version.MODEL_PACKAGES``), and a file added there renews the version of every model. At the first release of F5 (23 Oct
2026, 02:45 UTC) this module sat in ``fbi.predictions``, the fingerprint went from mc9a7bec97ca to mce0abbbb30d and the first pass
wrote 92,937 forecasts again under new versions. This module derives from what the models say and decides nothing about what any
of them predicts. Do not move it back (``tests/unit/test_model_code_version.py`` pins the fingerprint).
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.intel.calibration import CalibrationState, Calibrator, calibration_state
from fbi.models.scoring import MARKET_ROWS
from fbi.predictions.forecast import HORIZON, upcoming

VERSION: Final = "forecast-v1"

MAX_MARKET_AGE: Final = timedelta(hours=6)
"""A calibrator that takes the market's probability as an input gets the newest de-vigged consensus no older than this."""
MATERIAL_CHANGE: Final = Decimal("0.005")
"""A market is written again when any outcome moved by at least this (0.5 points) - or when its provenance changed."""

NOT_FIT: Final = frozenset({"PRODUCT_ONLY", "INSUFFICIENT"})
"""The competition data classes that are not fit for a model (the decision layer's ``NOT_FIT``; a test holds them equal)."""

FAMILIES: Final = {"1X2": "RESULT", "OU": "TOTAL_GOALS", "BTTS": "BOTH_TEAMS_SCORE"}
"""The forecast family of each market PrediGol forecasts. F10 adds goals by half, corners and cards."""

CALIBRATED: Final = "CALIBRATED"
UNCALIBRATED: Final = "UNCALIBRATED"

BASIS_CHAMPION: Final = "champion"
BASIS_NO_CHAMPION: Final = "no_champion"
BASIS_NEEDS_PRICE: Final = "needs_price"
BASIS_NOT_APPLICABLE: Final = "not_applicable"

_LO: Final = 1e-6


def _market_rows() -> dict[tuple[str, Decimal], tuple[str, ...]]:
    """(market, line) -> its outcomes, in the order the models price them."""
    out: dict[tuple[str, Decimal], list[str]] = defaultdict(list)
    for market, selection, line in MARKET_ROWS:
        out[(market, Decimal(str(line)))].append(selection)
    missing = {m for m, _ in out} - set(FAMILIES)
    assert not missing, f"a market the models price has no forecast family: {sorted(missing)}"
    return {k: tuple(v) for k, v in out.items()}


MARKETS: Final = _market_rows()
"""What is forecast: (market, line) -> outcomes. Derived from what the goal models price, so the two cannot drift apart."""


@dataclass(frozen=True, slots=True)
class Source:
    """One model's number for one outcome (a row of ``models.predictions``)."""

    model: str
    model_version_id: int
    data_cutoff_ts: datetime
    feature_set_hash: str
    p: float
    lo: float | None
    hi: float | None
    push: float


@dataclass(frozen=True, slots=True)
class Row:
    """A ``models.predictions`` row of the core markets, as the forecast reads it."""

    selection: str
    source: Source


@dataclass(frozen=True, slots=True)
class Outcome:
    selection: str
    p_model: float
    p: float
    lo: float | None
    hi: float | None
    push: float
    p_market: float | None = None
    market_as_of: datetime | None = None


@dataclass(frozen=True, slots=True)
class MarketForecast:
    """PrediGol's forecast of one market of one match: the outcomes (one model, one cut-off) and how they were calibrated."""

    fixture_id: int
    market_key: str
    line: Decimal
    model: str
    model_version_id: int
    data_cutoff_ts: datetime
    outcomes: tuple[Outcome, ...]
    calibration: str
    basis: str
    calibrator_id: int | None
    input_hash: str

    @property
    def family(self) -> str:
        return FAMILIES[self.market_key]


@dataclass(frozen=True, slots=True)
class Stored:
    """What was last written for a market: enough to tell whether a new forecast says anything new."""

    model: str
    model_version_id: int
    calibration: str
    calibrator_id: int | None
    p: dict[str, Decimal]


# ── the pure part ────────────────────────────────────────────────────────────────────────────────────────────────

def _clip(x: float) -> float:
    return min(max(x, _LO), 1 - _LO)


def _hash(parts: Sequence[object]) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def _calibrate(champion: Calibrator, outcomes: Sequence[Outcome]) -> tuple[list[Outcome], str] | None:
    """The champion applied to every outcome, the market scaled to add up to one. None when it cannot be applied."""
    cal: list[float] = []
    for o in outcomes:
        p = champion.apply(o.p_model, o.p_market)
        if p is None:
            return None
        cal.append(p)
    total = sum(cal)
    if total <= 0:
        return None
    out: list[Outcome] = []
    for o, p in zip(outcomes, cal, strict=True):
        ps = p / total
        lo = hi = None
        if o.lo is not None and o.hi is not None:
            cl = champion.apply(_clip(o.lo), o.p_market)
            ch = champion.apply(_clip(o.hi), o.p_market)
            if cl is not None and ch is not None:
                # a calibrator is monotone in the model's probability, but nothing here relies on the sign of its slope
                lo, hi = min(cl, ch) / total, max(cl, ch) / total
                lo, hi = min(lo, ps), max(hi, ps)
        out.append(Outcome(o.selection, o.p_model, ps, lo, hi, o.push, o.p_market, o.market_as_of))
    return out, BASIS_CHAMPION


def forecast_market(fixture_id: int, market_key: str, line: Decimal, models: dict[str, list[Row]],
                         cal: CalibrationState, market: dict[str, tuple[float, datetime]]) -> MarketForecast | None:
    """The forecast of one market, or None when no model priced every outcome of it.

    ``models``: model -> its rows for this market (every outcome, one cut-off); ``market``: outcome -> the newest de-vigged
    consensus probability and when it was captured, used only by a champion that takes the market as an input.
    """
    selections = MARKETS[(market_key, line)]
    complete: dict[str, list[Row]] = {}
    for name, rows in models.items():
        if sorted(r.selection for r in rows) != sorted(selections):
            continue
        # one version and one cut-off: the outcomes of a market are a set that adds up to one
        if len({(r.source.model_version_id, r.source.data_cutoff_ts) for r in rows}) != 1:
            continue
        complete[name] = rows
    if not complete:
        return None
    name = cal.primary_model(market_key, sorted(complete)) or sorted(complete)[0]
    by_sel = {r.selection: r.source for r in complete[name]}
    first = by_sel[selections[0]]
    raw = [Outcome(s, by_sel[s].p, by_sel[s].p, by_sel[s].lo, by_sel[s].hi, by_sel[s].push,
                   market.get(s, (None, None))[0], market.get(s, (None, None))[1]) for s in selections]
    champion = cal.champions.get((market_key, name))
    outcomes: tuple[Outcome, ...] = tuple(raw)
    calibration, basis, calibrator_id = UNCALIBRATED, BASIS_NO_CHAMPION, None
    if champion is not None:
        needs_market = champion.method == "logit2"
        if needs_market and any(o.p_market is None for o in raw):
            basis = BASIS_NEEDS_PRICE
        else:
            applied = _calibrate(champion, raw)
            if applied is None:
                basis = BASIS_NOT_APPLICABLE
            else:
                outcomes, basis = tuple(applied[0]), applied[1]
                calibration, calibrator_id = CALIBRATED, champion.id
    if calibration == UNCALIBRATED:
        # the market's probability is not part of an uncalibrated forecast: it is not stated, so it is not kept
        outcomes = tuple(Outcome(o.selection, o.p_model, o.p_model, o.lo, o.hi, o.push) for o in raw)
    digest = _hash([VERSION, fixture_id, market_key, str(line), name, first.model_version_id, first.data_cutoff_ts,
                    sorted((s, by_sel[s].feature_set_hash) for s in selections), calibrator_id, basis,
                    sorted((o.selection, None if o.p_market is None else round(o.p_market, 6)) for o in outcomes)])
    return MarketForecast(fixture_id, market_key, line, name, first.model_version_id, first.data_cutoff_ts, outcomes,
                          calibration, basis, calibrator_id, digest)


def says_something_new(previous: Stored | None, new: MarketForecast) -> bool:
    """Is this forecast worth a row? New market, another model, version or calibrator, or an outcome that moved."""
    if previous is None:
        return True
    if (previous.model, previous.model_version_id, previous.calibration, previous.calibrator_id) != (
            new.model, new.model_version_id, new.calibration, new.calibrator_id):
        return True
    if set(previous.p) != {o.selection for o in new.outcomes}:
        return True
    return any(abs(previous.p[o.selection] - Decimal(str(round(o.p, 6)))) >= MATERIAL_CHANGE for o in new.outcomes)


def most_likely(outcomes: Iterable[Outcome]) -> str | None:
    """The outcome with the highest probability (the first of them in the models' order if two tie)."""
    best: Outcome | None = None
    for o in outcomes:
        if best is None or o.p > best.p:
            best = o
    return None if best is None else best.selection


# ── reading and writing ──────────────────────────────────────────────────────────────────────────────────────────

SOURCES_SQL = """
WITH newest AS (
    SELECT DISTINCT ON (p.fixture_id, r.name) p.fixture_id, r.name AS model, p.model_version_id, p.data_cutoff_ts
      FROM models.predictions p JOIN models.model_versions v ON v.id = p.model_version_id
      JOIN models.model_registry r ON r.id = v.model_id
     WHERE p.fixture_id = ANY(%(ids)s) AND p.backtest_session_id IS NULL AND p.data_cutoff_ts <= %(at)s
     ORDER BY p.fixture_id, r.name, p.data_cutoff_ts DESC, p.model_version_id DESC
)
SELECT n.model, p.fixture_id, p.model_version_id, p.data_cutoff_ts, p.market_key, p.selection, p.line,
       p.p_raw::float8 AS p, p.p_lo::float8 AS lo, p.p_hi::float8 AS hi, COALESCE(p.p_push, 0)::float8 AS push,
       p.feature_set_hash
  FROM models.predictions p JOIN newest n ON n.fixture_id = p.fixture_id AND n.model_version_id = p.model_version_id
       AND n.data_cutoff_ts = p.data_cutoff_ts
 WHERE p.fixture_id = ANY(%(ids)s) AND p.backtest_session_id IS NULL
   AND (p.market_key, p.line) IN (SELECT c.m, c.l FROM unnest(%(core_markets)s::text[], %(core_lines)s::numeric[]) AS c(m, l))
"""
"""The newest real-time forecast of each model for each match, restricted to the core markets. ``p_raw`` is the model's own
number: ``p_calibrated`` is the same today, but ``p_raw`` is the one that means it."""

CONSENSUS_SQL = """
SELECT DISTINCT ON (m.fixture_id, m.market_key, m.selection, m.line)
       m.fixture_id, m.market_key, m.selection, m.line, m.p_fair::float8 AS p_fair, m.as_of
  FROM market.market_consensus m
 WHERE m.fixture_id = ANY(%(ids)s) AND m.devig_method = 'shin' AND m.as_of <= %(at)s AND m.as_of >= %(since)s
   AND m.p_fair > 0 AND m.p_fair < 1
   AND (m.market_key, m.line) IN (SELECT c.m, c.l FROM unnest(%(core_markets)s::text[], %(core_lines)s::numeric[]) AS c(m, l))
 ORDER BY m.fixture_id, m.market_key, m.selection, m.line, m.as_of DESC
"""

QUALITY_SQL = """
SELECT f.id AS fixture_id,
       (SELECT s.class FROM analytics.competition_data_scores s
         WHERE s.competition_season_id = f.competition_season_id AND s.computed_at <= %(at)s
         ORDER BY s.computed_at DESC LIMIT 1) AS data_class,
       EXISTS (SELECT 1 FROM analytics.fixture_validation v WHERE v.fixture_id = f.id AND v.state = 'QUARANTINED')
              AS quarantined
  FROM core.fixtures f WHERE f.id = ANY(%(ids)s)
"""

STORED_SQL = """
WITH last AS (
    SELECT fixture_id, market_key, line, max(known_at) AS k
      FROM models.match_forecasts
     WHERE fixture_id = ANY(%(ids)s) AND version = %(version)s AND known_at <= %(at)s
     GROUP BY 1, 2, 3
)
SELECT f.fixture_id, f.market_key, f.line, f.selection, f.p, f.model_name, f.model_version_id, f.calibration,
       f.calibrator_id
  FROM models.match_forecasts f JOIN last l ON l.fixture_id = f.fixture_id AND l.market_key = f.market_key
       AND l.line = f.line AND l.k = f.known_at
 WHERE f.version = %(version)s
"""

INSERT_SQL = """
INSERT INTO models.match_forecasts (version, known_at, fixture_id, family, market_key, selection, line, model_name,
       model_version_id, data_cutoff_ts, p_model, p, p_lo, p_hi, p_push, calibration, calibrator_id, p_market_used,
       market_as_of, basis, input_hash, code_version)
VALUES (%(version)s, %(known_at)s, %(fixture_id)s, %(family)s, %(market_key)s, %(selection)s, %(line)s, %(model_name)s,
        %(model_version_id)s, %(data_cutoff_ts)s, %(p_model)s, %(p)s, %(p_lo)s, %(p_hi)s, %(p_push)s, %(calibration)s,
        %(calibrator_id)s, %(p_market_used)s, %(market_as_of)s, %(basis)s, %(input_hash)s, %(code_version)s)
ON CONFLICT ON CONSTRAINT match_forecasts_once DO NOTHING
"""


@dataclass
class MatchForecastReport:
    at: datetime
    targets: int = 0
    with_model: int = 0
    not_fit: int = 0
    markets_written: int = 0
    rows_written: int = 0
    unchanged: int = 0
    calibrated: int = 0
    uncalibrated: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def summary(self) -> str:
        un = ", ".join(f"{k} {v}" for k, v in sorted(self.uncalibrated.items())) or "none"
        return (f"match forecasts {self.markets_written} markets written ({self.rows_written} rows)/{self.unchanged} unchanged "
                f"for {self.with_model} of {self.targets} fixtures ({self.not_fit} not fit); calibrated {self.calibrated}, "
                f"uncalibrated: {un}")


def _core() -> dict[str, list[Any]]:
    """The markets that are forecast, as the two parallel arrays the queries unnest (a row list cannot be a parameter)."""
    keys = sorted(MARKETS)
    return {"core_markets": [m for m, _ in keys], "core_lines": [line for _, line in keys]}


def _read_sources(conn: psycopg.Connection[Any], ids: list[int], at: datetime
                  ) -> dict[tuple[int, str, Decimal], dict[str, list[Row]]]:
    out: dict[tuple[int, str, Decimal], dict[str, list[Row]]] = defaultdict(lambda: defaultdict(list))
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(SOURCES_SQL, {"ids": ids, "at": at, **_core()})
        for r in cur.fetchall():
            line = Decimal(r["line"])
            if (str(r["market_key"]), line) not in MARKETS:
                continue
            out[(int(r["fixture_id"]), str(r["market_key"]), line)][str(r["model"])].append(Row(
                str(r["selection"]),
                Source(str(r["model"]), int(r["model_version_id"]), r["data_cutoff_ts"], str(r["feature_set_hash"]),
                       float(r["p"]), None if r["lo"] is None else float(r["lo"]),
                       None if r["hi"] is None else float(r["hi"]), float(r["push"]))))
    return out


def _read_consensus(conn: psycopg.Connection[Any], ids: list[int], at: datetime
                    ) -> dict[tuple[int, str, Decimal], dict[str, tuple[float, datetime]]]:
    out: dict[tuple[int, str, Decimal], dict[str, tuple[float, datetime]]] = defaultdict(dict)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(CONSENSUS_SQL, {"ids": ids, "at": at, "since": at - MAX_MARKET_AGE, **_core()})
        for r in cur.fetchall():
            out[(int(r["fixture_id"]), str(r["market_key"]), Decimal(r["line"]))][str(r["selection"])] = (
                float(r["p_fair"]), r["as_of"])
    return out


def _read_stored(conn: psycopg.Connection[Any], ids: list[int], at: datetime) -> dict[tuple[int, str, Decimal], Stored]:
    rows: dict[tuple[int, str, Decimal], list[dict[str, Any]]] = defaultdict(list)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(STORED_SQL, {"ids": ids, "at": at, "version": VERSION})
        for r in cur.fetchall():
            rows[(int(r["fixture_id"]), str(r["market_key"]), Decimal(r["line"]))].append(r)
    return {k: Stored(str(v[0]["model_name"]), int(v[0]["model_version_id"]), str(v[0]["calibration"]),
                      None if v[0]["calibrator_id"] is None else int(v[0]["calibrator_id"]),
                      {str(r["selection"]): Decimal(r["p"]) for r in v})
            for k, v in rows.items()}


def _fit_fixtures(conn: psycopg.Connection[Any], ids: list[int], at: datetime) -> set[int]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(QUALITY_SQL, {"ids": ids, "at": at})
        return {int(r["fixture_id"]) for r in cur.fetchall()
                if r["data_class"] not in NOT_FIT and not r["quarantined"]}


def fit_fixtures(conn: psycopg.Connection[Any], ids: list[int], at: datetime) -> set[int]:
    """The matches among ``ids`` whose competition's data is fit for a model and that are not quarantined (the gate every forecast passes)."""
    return _fit_fixtures(conn, ids, at)


def _q(x: float | None, places: int = 6) -> Decimal | None:
    return None if x is None else Decimal(str(round(x, places)))


def store(conn: psycopg.Connection[Any], f: MarketForecast, *, at: datetime, code_version: str, version: str = VERSION,
          family: str | None = None) -> int:
    """The rows of one market forecast (all its outcomes). Returns how many were written.

    ``version`` and ``family`` are those of the core markets unless the caller is another writer of the same table (``fbi.families``, F10):
    it writes under a version of its own, which the forecast of a match does not read (only the Admin Console's preview shows it, in a section of
    its own), and names the family of its keys."""
    written = 0
    with conn.cursor() as cur:
        for o in f.outcomes:
            cur.execute(INSERT_SQL, {
                "version": version, "known_at": at, "fixture_id": f.fixture_id, "family": family or f.family,
                "market_key": f.market_key, "selection": o.selection, "line": f.line, "model_name": f.model,
                "model_version_id": f.model_version_id, "data_cutoff_ts": f.data_cutoff_ts, "p_model": _q(o.p_model),
                "p": _q(o.p), "p_lo": _q(o.lo), "p_hi": _q(o.hi), "p_push": _q(o.push) or Decimal("0"),
                "calibration": f.calibration, "calibrator_id": f.calibrator_id,
                "p_market_used": _q(o.p_market) if f.calibration == CALIBRATED else None,
                "market_as_of": o.market_as_of if f.calibration == CALIBRATED else None, "basis": f.basis,
                "input_hash": f.input_hash, "code_version": code_version})
            written += max(cur.rowcount, 0)
    return written


def write_match_forecasts(conn: psycopg.Connection[Any], *, at: datetime, code_version: str,
                          horizon: timedelta = HORIZON, fixture_ids: list[int] | None = None) -> MatchForecastReport:
    """Forecast every upcoming match that has a model and write what is new. Database only: no provider request."""
    report = MatchForecastReport(at=at)
    ids = fixture_ids if fixture_ids is not None else upcoming(conn, at, horizon)
    report.targets = len(ids)
    if not ids:
        return report
    fit = _fit_fixtures(conn, ids, at)
    report.not_fit = len(ids) - len(fit)
    ids = [i for i in ids if i in fit]
    if not ids:
        return report
    cal = calibration_state(conn, at=at)
    sources = _read_sources(conn, ids, at)
    consensus = _read_consensus(conn, ids, at)
    stored = _read_stored(conn, ids, at)
    covered: set[int] = set()
    for key in sorted(sources):
        fixture_id, market_key, line = key
        forecast = forecast_market(fixture_id, market_key, line, sources[key], cal, consensus.get(key, {}))
        if forecast is None:
            continue
        covered.add(fixture_id)
        if not says_something_new(stored.get(key), forecast):
            report.unchanged += 1
            continue
        written = store(conn, forecast, at=at, code_version=code_version)
        if written == 0:  # the instant already holds this market (the same ``at`` run again): nothing to add
            report.unchanged += 1
            continue
        report.rows_written += written
        report.markets_written += 1
        if forecast.calibration == CALIBRATED:
            report.calibrated += 1
        else:
            report.uncalibrated[forecast.basis] += 1
    report.with_model = len(covered)
    return report
