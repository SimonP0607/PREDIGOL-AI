"""CAPA 4 - the decision layer (``decision-v1``): every candidate through ten filters to one state, with its PrediGol
Pick Score and its stake, written down at each checkpoint before kick-off (``intel.decisions``, append-only).

CANDIDATES. The selections the models flagged (``picks.picks``, shadow-rule-v2: the quantitative scan of every
market of every match) for matches in the next 36 hours. Per selection, the market's specialised model is used (the
one whose calibrator is champion with the lowest out-of-sample log loss, ``fbi.intel.calibration``); the other models
only vote (consensus). Everything is read AS OF the decision's moment ``known_at``: picks created by then, prices
captured by then, reviews and evidence retrieved by then, calibrators fitted by then.

THE TEN FILTERS (each recorded with its verdict and why):

     1 data          the match is still to play, >= 10 min away, its competition's data fit for models, not quarantined,
                     the model's forecast not older than 72 h                                     -> RECHAZADO
     2 model         the market's model gave a probability with its interval                      -> RECHAZADO
     3 market        a current price from >= 3 bookmakers, at most 3 h old, not an outlier (<= 25 % above the de-vigged
                     consensus); a stale price only parks the selection                           -> RECHAZADO / INVESTIGACION
     4 calibration   a CHAMPION calibrator for (market, model); otherwise the best fit is shown, never approved
                                                                                                  -> INVESTIGACION
     5 ev            calibrated EV >= 2 % and calibrated edge >= 1 point at the current best price -> RECHAZADO
     6 context       PrediGol Intelligence's newest review and evidence: an unplayable or quarantined match, or a key
                     absence on the chosen side once the line-ups are confirmed -> RECHAZADO; a key absence before the
                     line-ups, a review REJECT or DOWNGRADE -> CAUTELA; no outside context at all is "CONTEXTO EXTERNO
                     LIMITADO" - recorded and scored, never a rejection by itself              -> RECHAZADO / CAUTELA
     7 risk          price above 3.00 (risk-v1), calibrated probability below 0.30, model interval wider than 25
                     points                                                                       -> CAUTELA
     8 correlation   one selection per match: the others of the same match                        -> CAUTELA
     9 price         at T-90m and later the price must be at most 30 minutes old                  -> CAUTELA
    10 final         APROBADO only when the market's edge is validated out of sample (edge-gate-v1); otherwise the
                     candidate is measured in INVESTIGACION. An approved one is PICK_PREMIUM (score >= 80 and both the
                     market's and the pick type's closing-line value positive) or CANDIDATO_PARLAY (odds 1.25-2.20,
                     calibrated p >= 0.5). PICK_DEL_DIA is chosen later (``select_day``).

Precedence: RECHAZADO > INVESTIGACION > CAUTELA > APROBADO. A row is written when the selection is first seen, when its
checkpoint, state, calibrator or context changes, or when its price moves more than 3 %; a RECHAZADO selection is
written again only if its state changes. The same input twice writes nothing (``input_hash``).
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.ai.calendar import day_bounds, local_day
from fbi.core.version import code_version
from fbi.intel import score as scoring
from fbi.intel import stake as staking
from fbi.intel.calibration import CalibrationState, calibration_state

VERSION = "decision-v1"
HORIZON = timedelta(hours=36)
CONSENSUS_LOOKBACK = timedelta(hours=36)
MIN_MINUTES = 10
FORECAST_MAX_AGE = timedelta(hours=72)
MIN_BOOKS = 3
MAX_PRICE_AGE = timedelta(hours=3)
MAX_PRICE_EDGE = 0.25
EV_MIN = 0.02
EDGE_MIN = 0.01
RISK_MAX_ODDS = 3.00
RISK_MIN_P = 0.30
RISK_MAX_WIDTH = 0.25
FINAL_FRESH = timedelta(minutes=30)
PREMIUM_SCORE = 80.0
PARLAY_ODDS = (1.25, 2.20)
PARLAY_MIN_P = 0.5
PRICE_MOVE = 0.03
NOT_FIT = frozenset({"PRODUCT_ONLY", "INSUFFICIENT"})
BAD_STATUS = frozenset({"PST", "CANC", "ABD", "SUSP", "AWD", "WO", "INT"})
APPROVED = frozenset({"APROBADO", "CANDIDATO_PARLAY", "PICK_PREMIUM", "PICK_DEL_DIA"})
RANK = {"RECHAZADO": 0, "INVESTIGACION": 1, "CAUTELA": 2, "APROBADO": 3}
FINAL_CHECKPOINTS = frozenset({"T-90m", "lineups", "T-60m", "T-15m"})
STOP_CODES = frozenset({"fixture_not_playable", "fixture_quarantined", "data_not_model_ready"})

Key = tuple[int, str, str, Decimal]


def checkpoint_of(minutes: float, *, important: bool, lineups: bool) -> str:
    """The checkpoint a selection is at: T-36h ... T-60m, 'lineups' once the line-ups are in (from 100 min), and
    T-15m only for the important ones (approved, pick of the day, premium)."""
    if minutes <= 15 and important:
        return "T-15m"
    if lineups and minutes <= 100:
        return "lineups"
    for limit, label in ((60, "T-60m"), (90, "T-90m"), (180, "T-3h"), (360, "T-6h"), (720, "T-12h"),
                         (1440, "T-24h")):
        if minutes <= limit:
            return label
    return "T-36h"


def ev_of(p: float, odds: float, p_push: float = 0.0) -> float:
    """Expected value per unit staked: (1 - p_push)(p * odds - 1), p conditional on the bet settling."""
    return (1.0 - p_push) * (p * odds - 1.0)


# ── reading what is known at ``at`` ──────────────────────────────────────────────────────────────────────────────

CANDIDATES_SQL = """
WITH fx AS (
    SELECT f.id FROM core.fixtures f WHERE f.kickoff_at > %(at)s AND f.kickoff_at < %(until)s
       AND (%(only)s::bigint[] IS NULL OR f.id = ANY(%(only)s))
), lp AS (
    SELECT DISTINCT ON (p.fixture_id, p.market_key, p.selection, p.line, r.name)
           p.id AS pick_id, p.fixture_id, p.market_key, p.selection, p.line, r.name AS model_name,
           v.status AS model_status, p.model_version_id, p.p_calibrated::float8 AS p_model,
           COALESCE(p.p_push, 0)::float8 AS p_push, p.p_calibrated_lo::float8 AS p_low,
           p.p_calibrated_hi::float8 AS p_high, p.created_at AS pick_created_at, p.data_cutoff_ts
      FROM picks.picks p JOIN fx ON fx.id = p.fixture_id
      JOIN models.model_versions v ON v.id = p.model_version_id
      JOIN models.model_registry r ON r.id = v.model_id
     WHERE p.created_at <= %(at)s
     ORDER BY p.fixture_id, p.market_key, p.selection, p.line, r.name, p.created_at DESC, p.id DESC
), lc AS (
    SELECT DISTINCT ON (m.fixture_id, m.market_key, m.selection, m.line)
           m.fixture_id, m.market_key, m.selection, m.line, m.p_fair::float8 AS p_fair,
           m.best_odds::float8 AS best_odds, m.best_bookmaker_id, m.n_bookmakers, m.overround::float8 AS overround,
           m.dispersion::float8 AS dispersion, m.as_of
      FROM market.market_consensus m JOIN fx ON fx.id = m.fixture_id
     WHERE m.devig_method = 'shin' AND m.as_of <= %(at)s AND m.as_of >= %(since)s
     ORDER BY m.fixture_id, m.market_key, m.selection, m.line, m.as_of DESC
)
SELECT lp.*, f.kickoff_at, f.status_short, f.status_group, f.home_team_id, f.away_team_id, f.competition_season_id,
       cs.competition_id, c.name AS competition_name, th.name AS home_name, ta.name AS away_name,
       lc.p_fair, lc.best_odds, lc.best_bookmaker_id, lc.n_bookmakers, lc.overround, lc.dispersion,
       lc.as_of AS price_at
  FROM lp
  JOIN core.fixtures f ON f.id = lp.fixture_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
  LEFT JOIN lc ON lc.fixture_id = lp.fixture_id AND lc.market_key = lp.market_key AND lc.selection = lp.selection
              AND lc.line = lp.line
"""

QUALITY_SQL = """
SELECT f.id AS fixture_id, s.class AS data_class, (v.state = 'QUARANTINED') AS quarantined
  FROM core.fixtures f
  LEFT JOIN analytics.competition_data_scores s ON s.competition_season_id = f.competition_season_id
       AND s.computed_at <= %(at)s
  LEFT JOIN analytics.fixture_validation v ON v.fixture_id = f.id
 WHERE f.id = ANY(%(fixtures)s)
"""

REVIEWS_SQL = """
SELECT DISTINCT ON (r.fixture_id, r.market_key, r.selection, r.line, r.engine)
       r.id, r.engine, r.fixture_id, r.market_key, r.selection, r.line, r.decision, r.confidence, r.reviewed_at,
       r.engine_version, r.output, r.evidence_ids, r.cost_usd
  FROM ai.pick_reviews r
 WHERE r.fixture_id = ANY(%(fixtures)s) AND r.engine IN ('combined', 'rules') AND r.reviewed_at <= %(at)s
   AND r.reviewed_at >= %(at)s - interval '12 hours'
 ORDER BY r.fixture_id, r.market_key, r.selection, r.line, r.engine, r.reviewed_at DESC, r.id DESC
"""

EVIDENCE_SQL = """
SELECT e.fixture_id, e.origin, e.status, e.source_tier, count(*) AS n, array_agg(e.id ORDER BY e.id) AS ids
  FROM ai.evidence e
 WHERE e.fixture_id = ANY(%(fixtures)s) AND e.retrieved_at <= %(at)s
   AND (e.published_at IS NULL OR e.published_at <= %(at)s)
 GROUP BY 1, 2, 3, 4
"""

PASSES_SQL = """
SELECT p.fixture_id, bool_or(p.pass = 'first') AS first_done,
       bool_or(COALESCE((p.counts->>'web_searches')::int, 0) > 0) AS searched, max(p.finished_at) AS last_pass
  FROM ai.fixture_passes p
 WHERE p.fixture_id = ANY(%(fixtures)s) AND p.finished_at <= %(at)s AND p.status IN ('ok', 'partial')
 GROUP BY 1
"""

LINEUPS_SQL = """
SELECT fixture_id, max(fetched_at) AS fetched_at FROM core.fixture_lineups
 WHERE fixture_id = ANY(%(fixtures)s) AND fetched_at <= %(at)s GROUP BY 1
"""

TYPE_CLV_SQL = """
SELECT p.market_key, p.selection,
       CASE WHEN p.market_odds < 1.8 THEN 'a' WHEN p.market_odds < 2.5 THEN 'b' WHEN p.market_odds < 3.5 THEN 'c'
            ELSE 'd' END AS band,
       avg(lv.lv_devigged)::float8 AS clv, count(*) AS n
  FROM picks.picks p
  JOIN picks.pick_line_value lv ON lv.pick_id = p.id
  JOIN core.fixtures f ON f.id = p.fixture_id
 WHERE f.kickoff_at >= %(since)s AND f.kickoff_at < %(at)s AND lv.computed_at <= %(at)s AND lv.lv_devigged IS NOT NULL
 GROUP BY 1, 2, 3
"""

PREVIOUS_SQL = """
SELECT DISTINCT ON (fixture_id, market_key, selection, line) id, fixture_id, market_key, selection, line, checkpoint,
       state, odds::float8 AS odds, calibrator_id, context_status, input_hash, known_at, score
  FROM intel.decisions
 WHERE fixture_id = ANY(%(fixtures)s) AND known_at <= %(at)s AND decision_version = %(version)s
 ORDER BY fixture_id, market_key, selection, line, known_at DESC, id DESC
"""


def odds_band(odds: float) -> str:
    return "a" if odds < 1.8 else "b" if odds < 2.5 else "c" if odds < 3.5 else "d"


def side_of(market: str, selection: str) -> str:
    if market in ("1X2", "AH"):
        return "home" if selection == "Home" else "away" if selection == "Away" else "draw"
    if market == "DC":
        return "home" if selection == "1X" else "away" if selection == "X2" else "draw"
    return "total"


@dataclass
class Context:
    """What PrediGol Intelligence knew about a match (and a selection) at the decision's moment."""

    status: str
    first_pass: bool = False
    searched: bool = False
    lineups_at: datetime | None = None
    evidence: dict[str, int] = field(default_factory=dict)
    evidence_ids: list[int] = field(default_factory=list)
    review: dict[str, Any] | None = None
    rules_codes: dict[str, str] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        r = self.review
        return {"status": self.status, "limited": self.status == "LIMITED", "first_pass": self.first_pass,
                "web_searched": self.searched, "lineups_at": None if self.lineups_at is None else self.lineups_at.isoformat(),
                "evidence": self.evidence, "signals": self.rules_codes,
                "review": None if r is None else {"id": int(r["id"]), "decision": r["decision"],
                                                  "confidence": float(r["confidence"]),
                                                  "engine_version": r["engine_version"],
                                                  "reviewed_at": r["reviewed_at"].isoformat(),
                                                  "reason": (r.get("output") or {}).get("reason")}}


def context_status(*, ai_mode: str, first_pass: bool, reviewed: bool, searched: bool, web_good: int,
                   provider_items: int, lineups: bool) -> str:
    """FULL: read, with web evidence from a known source or the confirmed line-ups after a search; PARTIAL: read, with
    the provider's reports only; LIMITED: read and nothing found outside the numbers (CONTEXTO EXTERNO LIMITADO);
    PENDING: not read yet; AI_OFF: the layer is switched off."""
    if ai_mode == "off":
        return "AI_OFF"
    if not first_pass and not reviewed:
        return "PENDING"
    if web_good > 0 or (searched and lineups):
        return "FULL"
    if provider_items > 0 or lineups:
        return "PARTIAL"
    return "LIMITED"


@dataclass
class Evaluated:
    key: Key
    row: dict[str, Any]
    checkpoint: str
    state: str
    reasons: list[str]
    filters: list[dict[str, Any]]
    p_cal: float | None
    calibrator_id: int | None
    calibrator_role: str | None
    ev_raw: float | None
    edge_raw: float | None
    ev_cal: float | None
    edge_cal: float | None
    score: scoring.Score | None
    stake: staking.Stake
    context: Context
    premium: bool = False
    parlay_eligible: bool = False
    consensus: dict[str, Any] = field(default_factory=dict)


def _f(name: str, ok: bool | None, why: str, effect: str | None = None, n: int = 0, **data: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"n": n, "key": name, "ok": ok, "why": why}
    if effect is not None and ok is False:
        out["effect"] = effect
    if data:
        out["data"] = data
    return out


@dataclass
class World:
    """Everything a run reads once."""

    at: datetime
    cal: CalibrationState
    quality: dict[int, dict[str, Any]]
    reviews: dict[Key, dict[str, Any]]
    rules: dict[Key, dict[str, Any]]
    evidence: dict[int, list[dict[str, Any]]]
    passes: dict[int, dict[str, Any]]
    lineups: dict[int, datetime]
    type_clv: dict[tuple[str, str, str], tuple[float, int]]
    previous: dict[Key, dict[str, Any]]
    ai_mode: str


LINE_Q = Decimal("0.01")


def _key(r: dict[str, Any]) -> Key:
    return int(r["fixture_id"]), str(r["market_key"]), str(r["selection"]), Decimal(str(r["line"])).quantize(LINE_Q)


def read_world(conn: psycopg.Connection[Any], fixtures: list[int], *, at: datetime) -> World:
    from fbi.ai.config import AiSettings

    cal = calibration_state(conn, at=at)
    quality: dict[int, dict[str, Any]] = {}
    reviews: dict[Key, dict[str, Any]] = {}
    rules: dict[Key, dict[str, Any]] = {}
    evidence: dict[int, list[dict[str, Any]]] = defaultdict(list)
    passes: dict[int, dict[str, Any]] = {}
    lineups: dict[int, datetime] = {}
    type_clv: dict[tuple[str, str, str], tuple[float, int]] = {}
    previous: dict[Key, dict[str, Any]] = {}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(QUALITY_SQL, {"fixtures": fixtures, "at": at})
        quality = {int(r["fixture_id"]): dict(r) for r in cur.fetchall()}
        cur.execute(LINEUPS_SQL, {"fixtures": fixtures, "at": at})
        lineups = {int(r["fixture_id"]): r["fetched_at"] for r in cur.fetchall()}
        cur.execute(TYPE_CLV_SQL, {"since": at - timedelta(days=30), "at": at})
        type_clv = {(str(r["market_key"]), str(r["selection"]), str(r["band"])): (float(r["clv"]), int(r["n"]))
                    for r in cur.fetchall()}
        cur.execute(PREVIOUS_SQL, {"fixtures": fixtures, "at": at, "version": VERSION})
        previous = {_key(r): dict(r) for r in cur.fetchall()}
    try:
        with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            cur.execute(REVIEWS_SQL, {"fixtures": fixtures, "at": at})
            for r in cur.fetchall():
                (reviews if r["engine"] == "combined" else rules)[_key(r)] = dict(r)
            cur.execute(EVIDENCE_SQL, {"fixtures": fixtures, "at": at})
            for r in cur.fetchall():
                evidence[int(r["fixture_id"])].append(dict(r))
            cur.execute(PASSES_SQL, {"fixtures": fixtures, "at": at})
            passes = {int(r["fixture_id"]): dict(r) for r in cur.fetchall()}
    except psycopg.errors.UndefinedTable:
        pass
    return World(at, cal, quality, reviews, rules, dict(evidence), passes, lineups, type_clv, previous,
                 AiSettings.from_env().mode)


def load_candidates(conn: psycopg.Connection[Any], *, at: datetime, horizon: timedelta = HORIZON,
                    only: list[int] | None = None) -> dict[Key, dict[str, dict[str, Any]]]:
    """Per selection, the newest pick of each model (as of ``at``) with the newest consensus price."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(CANDIDATES_SQL, {"at": at, "until": at + horizon, "since": at - CONSENSUS_LOOKBACK,
                                     "only": only})
        rows = cur.fetchall()
    out: dict[Key, dict[str, dict[str, Any]]] = defaultdict(dict)
    for r in rows:
        out[_key(r)][str(r["model_name"])] = dict(r)
    return dict(out)


def build_context(world: World, key: Key, *, lineups_seen: bool) -> Context:
    fid = key[0]
    items = world.evidence.get(fid, [])
    counts: dict[str, int] = defaultdict(int)
    ids: list[int] = []
    web_good = provider_items = 0
    for e in items:
        n = int(e["n"])
        counts[f"{e['origin']}:{e['status']}"] += n
        if e["status"] != "OUTDATED":
            ids.extend(int(i) for i in (e["ids"] or [])[:20])
        if e["origin"] == "web" and e["status"] in ("CONFIRMED", "PROBABLE") and \
                e["source_tier"] in ("official", "competition", "club", "journalist", "media"):
            web_good += n
        if e["origin"] == "provider" and e["status"] in ("CONFIRMED", "PROBABLE"):
            provider_items += n
    p = world.passes.get(fid) or {}
    review = world.reviews.get(key)
    rules = world.rules.get(key)
    codes: dict[str, str] = {}
    if rules is not None:
        out = rules.get("output") or {}
        for group in ("negative_evidence", "uncertainties", "contradictions", "positive_evidence"):
            for c in out.get(group) or []:
                if isinstance(c, dict) and c.get("code"):
                    codes[str(c["code"])] = str(c.get("severity") or group)
    status = context_status(ai_mode=world.ai_mode, first_pass=bool(p.get("first_done")),
                            reviewed=review is not None, searched=bool(p.get("searched")), web_good=web_good,
                            provider_items=provider_items, lineups=lineups_seen)
    return Context(status, bool(p.get("first_done")), bool(p.get("searched")), world.lineups.get(fid),
                   dict(counts), sorted(set(ids))[:60], review, codes)


# ── one selection ────────────────────────────────────────────────────────────────────────────────────────────────

def evaluate(world: World, key: Key, models: dict[str, dict[str, Any]]) -> Evaluated:
    at = world.at
    market = key[1]
    model = world.cal.primary_model(market, sorted(models)) or sorted(models)[0]
    r = models[model]
    kickoff: datetime = r["kickoff_at"]
    minutes = (kickoff - at).total_seconds() / 60
    prev = world.previous.get(key)
    important = prev is not None and prev["state"] in APPROVED
    lineups_seen = key[0] in world.lineups
    cp = checkpoint_of(minutes, important=important, lineups=lineups_seen)
    ctx = build_context(world, key, lineups_seen=lineups_seen)
    filters: list[dict[str, Any]] = []
    effects: list[tuple[str, str]] = []

    def stop(state: str, reason: str) -> None:
        effects.append((state, reason))

    # 1 data
    q = world.quality.get(key[0]) or {}
    data_class = q.get("data_class")
    forecast_age = at - r["data_cutoff_ts"] if r.get("data_cutoff_ts") else None
    problems = []
    if (r.get("status_short") or "") in BAD_STATUS or r.get("status_group") not in (None, "scheduled"):
        problems.append(f"estado {r.get('status_short')}")
    if minutes < MIN_MINUTES:
        problems.append("menos de 10 min al saque")
    if data_class in NOT_FIT:
        problems.append(f"datos de la competición {data_class}")
    if q.get("quarantined"):
        problems.append("partido en cuarentena")
    if forecast_age is not None and forecast_age > FORECAST_MAX_AGE:
        problems.append(f"pronóstico de hace {forecast_age.total_seconds() / 3600:.0f} h")
    filters.append(_f("data", not problems, "; ".join(problems) or f"datos {data_class or 'sin evaluar'}",
                      "RECHAZADO", 1))
    if problems:
        stop("RECHAZADO", "data")

    # 2 model
    p_model = float(r["p_model"])
    p_push = float(r.get("p_push") or 0)
    has_interval = r.get("p_low") is not None and r.get("p_high") is not None
    filters.append(_f("model", has_interval and 0 < p_model < 1,
                      f"{model}: p {p_model:.3f}" + ("" if has_interval else " sin intervalo"), "RECHAZADO", 2,
                      model=model, model_version_id=r.get("model_version_id")))
    if not (has_interval and 0 < p_model < 1):
        stop("RECHAZADO", "model")
    width = (float(r["p_high"]) - float(r["p_low"])) if has_interval else None

    # 3 market
    odds = None if r.get("best_odds") is None else float(r["best_odds"])
    p_mkt = None if r.get("p_fair") is None else float(r["p_fair"])
    price_at: datetime | None = r.get("price_at")
    n_books = None if r.get("n_bookmakers") is None else int(r["n_bookmakers"])
    price_age = None if price_at is None else at - price_at
    price_edge = None if odds is None or p_mkt is None else odds * p_mkt - 1
    if odds is None or p_mkt is None:
        filters.append(_f("market", False, "sin precio de mercado observado", "RECHAZADO", 3))
        stop("RECHAZADO", "no_price")
    elif (n_books or 0) < MIN_BOOKS:
        filters.append(_f("market", False, f"solo {n_books} casas", "RECHAZADO", 3, n_bookmakers=n_books))
        stop("RECHAZADO", "thin_market")
    elif price_edge is not None and price_edge > MAX_PRICE_EDGE:
        filters.append(_f("market", False, f"precio atípico ({price_edge:+.0%} sobre el consenso)", "RECHAZADO", 3))
        stop("RECHAZADO", "price_outlier")
    elif price_age is not None and price_age > MAX_PRICE_AGE:
        filters.append(_f("market", False, f"precio de hace {price_age.total_seconds() / 3600:.1f} h",
                          "INVESTIGACION", 3))
        stop("INVESTIGACION", "price_stale")
    else:
        filters.append(_f("market", True, f"{n_books} casas, cuota {odds:.2f}, margen "
                          + ("?" if r.get("overround") is None else f"{float(r['overround']):.1%}"), n=3,
                          odds=odds, p_market=p_mkt, n_bookmakers=n_books))

    # 4 calibration
    champion = world.cal.champions.get((market, model))
    calibrator = champion or world.cal.best.get((market, model))
    p_cal = None if calibrator is None else calibrator.apply(p_model, p_mkt)
    wf = world.cal.wf.get((market, model)) or {}
    if champion is not None and p_cal is not None:
        filters.append(_f("calibration", True, f"calibrador {champion.method} #{champion.id} (champion), "
                          f"ECE {wf.get('ece_cal')}", n=4, calibrator_id=champion.id))
    else:
        why = ("sin calibrador validado: se muestra el mejor ajuste, no aprueba" if calibrator is not None
               else "sin calibrador para este mercado y modelo")
        filters.append(_f("calibration", False, why, "INVESTIGACION", 4,
                          calibrator_id=None if calibrator is None else calibrator.id))
        stop("INVESTIGACION", "not_calibrated")

    # 5 ev (at the current best price)
    ev_raw = None if odds is None else ev_of(p_model, odds, p_push)
    edge_raw = None if p_mkt is None else p_model - p_mkt
    ev_cal = None if odds is None or p_cal is None else ev_of(p_cal, odds, p_push)
    edge_cal = None if p_mkt is None or p_cal is None else p_cal - p_mkt
    if ev_cal is None:
        filters.append(_f("ev", None, "sin probabilidad calibrada o sin precio: EV no evaluable", n=5,
                          ev_raw=ev_raw))
        if odds is not None:
            stop("INVESTIGACION", "ev_unknown")
    elif ev_cal >= EV_MIN and (edge_cal or 0) >= EDGE_MIN:
        filters.append(_f("ev", True, f"EV calibrado {ev_cal:+.1%}, edge {edge_cal:+.3f} (crudo {ev_raw:+.1%})",
                          n=5, ev_cal=ev_cal, edge_cal=edge_cal, ev_raw=ev_raw))
    else:
        filters.append(_f("ev", False, f"EV calibrado {ev_cal:+.1%} / edge {edge_cal:+.3f} bajo el mínimo "
                          f"(crudo {ev_raw:+.1%})", "RECHAZADO", 5, ev_cal=ev_cal, edge_cal=edge_cal, ev_raw=ev_raw))
        stop("RECHAZADO", "ev_cal_below")

    # 6 context
    hard = [c for c, s in ctx.rules_codes.items() if s == "hard"]
    soft = [c for c, s in ctx.rules_codes.items() if s == "soft"]
    review_decision = None if ctx.review is None else str(ctx.review["decision"])
    if any(c in STOP_CODES for c in hard):
        filters.append(_f("context", False, "el contexto impide jugarlo: " + ", ".join(c for c in hard if c in STOP_CODES),
                          "RECHAZADO", 6))
        stop("RECHAZADO", "context_stop")
    elif "key_absences_pick_side" in hard and lineups_seen:
        filters.append(_f("context", False, "baja clave confirmada en el lado elegido (alineaciones)", "RECHAZADO", 6))
        stop("RECHAZADO", "key_absence_confirmed")
    elif "key_absences_pick_side" in hard:
        filters.append(_f("context", False, "baja clave reportada en el lado elegido (sin confirmar)", "CAUTELA", 6))
        stop("CAUTELA", "key_absence_reported")
    elif review_decision in ("REJECT", "DOWNGRADE"):
        filters.append(_f("context", False, f"revisión de PrediGol Intelligence: {review_decision} - "
                          + str((ctx.review or {}).get("output", {}).get("reason") or "")[:160], "CAUTELA", 6))
        stop("CAUTELA", f"ai_{review_decision.lower()}")
    else:
        label = {"LIMITED": "CONTEXTO EXTERNO LIMITADO: no se encontró información externa (no se inventa, no se "
                            "rechaza)", "PENDING": "PrediGol Intelligence aún no leyó el partido",
                 "AI_OFF": "capa de IA apagada"}.get(ctx.status, f"contexto {ctx.status}")
        filters.append(_f("context", True, label + (f"; revisión {review_decision}" if review_decision else ""),
                          n=6, context_status=ctx.status))
    if ctx.status == "LIMITED":
        # recorded, never a rejection by itself
        pass

    # 7 risk
    risks = []
    if odds is not None and odds > RISK_MAX_ODDS:
        risks.append(f"cuota {odds:.2f} > {RISK_MAX_ODDS:.2f}")
    if p_cal is not None and p_cal < RISK_MIN_P:
        risks.append(f"p calibrada {p_cal:.2f} < {RISK_MIN_P:.2f}")
    if width is not None and width > RISK_MAX_WIDTH:
        risks.append(f"intervalo {width * 100:.0f} pts")
    filters.append(_f("risk", not risks, "; ".join(risks) or "sin riesgo cuantitativo", "CAUTELA", 7))
    if risks:
        stop("CAUTELA", "risk")

    # 9 price freshness at the end
    if cp in FINAL_CHECKPOINTS and price_age is not None and price_age > FINAL_FRESH:
        filters.append(_f("price", False, f"precio de hace {price_age.total_seconds() / 60:.0f} min en {cp}",
                          "CAUTELA", 9))
        stop("CAUTELA", "price_not_fresh")
    else:
        filters.append(_f("price", True if odds is not None else None,
                          "EV recalculado con el mejor precio vigente" if odds is not None else "sin precio", n=9))

    # consensus of the other models
    others = []
    for name, orow in models.items():
        if name == model or orow.get("p_model") is None:
            continue
        oc = world.cal.for_model(market, name)
        po = float(orow["p_model"])
        pc = oc.apply(po, p_mkt) if oc is not None else po
        others.append({"model": name, "p": round(po, 4), "p_cal": None if pc is None else round(pc, 4),
                       "above_market": None if pc is None or p_mkt is None else pc > p_mkt})
    votes = [o["above_market"] for o in others if o["above_market"] is not None]
    consensus_share = (sum(1 for v in votes if v) / len(votes)) if votes else None

    # the score (only when there is something to score)
    sc: scoring.Score | None = None
    if odds is not None and p_cal is not None:
        tc = world.type_clv.get((market, key[2], odds_band(odds)))
        sc = scoring.score(scoring.ScoreInputs(
            ev_cal=ev_cal, edge_cal=edge_cal, ece=_num(wf.get("ece_cal")), rule_clv=_num(wf.get("rule_clv")),
            data_class=data_class, quarantined=bool(q.get("quarantined")),
            price_age_min=None if price_age is None else price_age.total_seconds() / 60, n_bookmakers=n_books,
            overround=None if r.get("overround") is None else float(r["overround"]), context_status=ctx.status,
            consensus=consensus_share, width=width, review_decision=review_decision, hard_signals=len(hard),
            soft_signals=len(soft), type_clv=None if tc is None or tc[1] < 50 else tc[0]))

    # 10 final
    edge_ok = bool(world.cal.edge.get((market, model)))
    worst = min((RANK[s] for s, _ in effects), default=RANK["APROBADO"])
    state = next(s for s, v in RANK.items() if v == worst)
    reasons = [why for s, why in effects]
    premium = parlay = False
    if state == "APROBADO" and not edge_ok:
        state = "INVESTIGACION"
        reasons.append("edge_not_validated")
        filters.append(_f("final", False, "el mercado no tiene edge validado fuera de muestra (edge-gate-v1): se mide "
                          "en investigación", "INVESTIGACION", 10))
    elif state == "APROBADO":
        tc = world.type_clv.get((market, key[2], odds_band(odds or 0)))
        premium = bool(sc is not None and sc.total >= PREMIUM_SCORE and (_num(wf.get("rule_clv")) or 0) > 0
                       and tc is not None and tc[0] > 0)
        parlay = odds is not None and PARLAY_ODDS[0] <= odds <= PARLAY_ODDS[1] and (p_cal or 0) >= PARLAY_MIN_P
        state = "PICK_PREMIUM" if premium else "CANDIDATO_PARLAY" if parlay else "APROBADO"
        filters.append(_f("final", True, f"aprobado ({state})", n=10))
    else:
        filters.append(_f("final", False, f"{state}: " + ", ".join(reasons), state, 10))
    st = staking.stake_for(state, p_cal, odds, p_push)
    return Evaluated(key, r | {"model_used": model}, cp, state, reasons, sorted(filters, key=lambda f: f["n"]), p_cal,
                     None if calibrator is None else calibrator.id, None if calibrator is None else calibrator.role,
                     ev_raw, edge_raw, ev_cal, edge_cal, sc, st, ctx, premium, parlay,
                     {"share": consensus_share, "others": others})


def _num(x: Any) -> float | None:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def correlate(evaluated: list[Evaluated]) -> None:
    """Filter 8: one selection per match. Among a match's approved selections the best score stays; the others
    become CAUTELA (``correlated_same_match``)."""
    by_fixture: dict[int, list[Evaluated]] = defaultdict(list)
    for e in evaluated:
        if e.state in APPROVED:
            by_fixture[e.key[0]].append(e)
    for xs in by_fixture.values():
        if len(xs) < 2:
            continue
        xs.sort(key=lambda e: -(e.score.total if e.score else 0))
        for e in xs[1:]:
            e.state = "CAUTELA"
            e.premium = e.parlay_eligible = False
            e.reasons.append("correlated_same_match")
            e.filters.append(_f("correlation", False, f"otra selección del mismo partido tiene mejor score "
                                f"({xs[0].key[1]} {xs[0].key[2]})", "CAUTELA", 8))
            e.stake = staking.stake_for("CAUTELA", e.p_cal, None if e.row.get("best_odds") is None
                                        else float(e.row["best_odds"]), float(e.row.get("p_push") or 0))
            e.filters.sort(key=lambda f: f["n"])
    for e in evaluated:
        if not any(f["key"] == "correlation" for f in e.filters):
            e.filters.append(_f("correlation", True, "única selección aprobable del partido", n=8))
            e.filters.sort(key=lambda f: f["n"])


def input_hash(e: Evaluated) -> str:
    odds = e.row.get("best_odds")
    payload = {"v": VERSION, "cp": e.checkpoint, "state": e.state,
               "odds": None if odds is None else round(float(odds), 2),
               "p_model": round(float(e.row["p_model"]), 4), "p_cal": None if e.p_cal is None else round(e.p_cal, 4),
               "cal": e.calibrator_id, "p_mkt": None if e.row.get("p_fair") is None else round(float(e.row["p_fair"]), 4),
               "ctx": e.context.status, "review": None if e.context.review is None else int(e.context.review["id"]),
               "pick": int(e.row["pick_id"])}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:32]


def should_write(e: Evaluated, prev: dict[str, Any] | None) -> bool:
    if prev is None:
        return True
    if prev["state"] != e.state:
        return True
    if e.state == "RECHAZADO":
        return False
    if prev["checkpoint"] != e.checkpoint or prev["calibrator_id"] != e.calibrator_id \
            or prev["context_status"] != e.context.status:
        return True
    odds = e.row.get("best_odds")
    if odds is not None and prev.get("odds"):
        return abs(float(odds) / float(prev["odds"]) - 1) > PRICE_MOVE
    return False


INSERT_SQL = """
INSERT INTO intel.decisions (decision_version, known_at, checkpoint, fixture_id, kickoff_at, market_key, selection, line,
    pick_id, model_name, model_version_id, odds, bookmaker_id, price_at, n_bookmakers, p_model, p_low, p_high, p_push,
    p_cal, calibrator_id, calibrator_role, p_market, ev_raw, edge_raw, ev_cal, edge_cal, filters, state, reasons,
    premium, parlay_eligible, score, score_version, score_components, stake_units, stake_version, stake_components,
    context_status, context, review_id, evidence_ids, input_hash, code_version)
VALUES (%(v)s, %(at)s, %(cp)s, %(fixture)s, %(kickoff)s, %(market)s, %(selection)s, %(line)s, %(pick)s, %(model)s,
    %(mv)s, %(odds)s, %(bookmaker)s, %(price_at)s, %(books)s, %(p_model)s, %(p_low)s, %(p_high)s, %(p_push)s, %(p_cal)s,
    %(cal)s, %(cal_role)s, %(p_market)s, %(ev_raw)s, %(edge_raw)s, %(ev_cal)s, %(edge_cal)s, %(filters)s, %(state)s,
    %(reasons)s, %(premium)s, %(parlay)s, %(score)s, %(score_v)s, %(score_c)s, %(stake)s, %(stake_v)s, %(stake_c)s,
    %(ctx_status)s, %(ctx)s, %(review)s, %(evidence)s, %(hash)s, %(code)s)
ON CONFLICT DO NOTHING RETURNING id
"""


def _d(x: float | None, places: int = 6) -> Decimal | None:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    return Decimal(str(round(x, places)))


def store(conn: psycopg.Connection[Any], e: Evaluated, *, at: datetime, checkpoint: str | None = None,
          state: str | None = None, stake: staking.Stake | None = None) -> int | None:
    r = e.row
    rejected = (state or e.state) == "RECHAZADO"
    st = stake or e.stake
    cp = checkpoint or e.checkpoint
    with conn.cursor() as cur:
        cur.execute(INSERT_SQL, {
            "v": VERSION, "at": at, "cp": cp, "fixture": e.key[0], "kickoff": r["kickoff_at"], "market": e.key[1],
            "selection": e.key[2], "line": e.key[3], "pick": int(r["pick_id"]), "model": r["model_used"],
            "mv": r.get("model_version_id"), "odds": _d(None if r.get("best_odds") is None else float(r["best_odds"]), 3),
            "bookmaker": r.get("best_bookmaker_id"), "price_at": r.get("price_at"), "books": r.get("n_bookmakers"),
            "p_model": _d(float(r["p_model"])), "p_low": _d(_num(r.get("p_low"))), "p_high": _d(_num(r.get("p_high"))),
            "p_push": _d(_num(r.get("p_push"))), "p_cal": _d(e.p_cal), "cal": e.calibrator_id,
            "cal_role": e.calibrator_role, "p_market": _d(_num(r.get("p_fair"))), "ev_raw": _d(e.ev_raw),
            "edge_raw": _d(e.edge_raw), "ev_cal": _d(e.ev_cal), "edge_cal": _d(e.edge_cal),
            "filters": Jsonb(e.filters), "state": state or e.state, "reasons": e.reasons, "premium": e.premium,
            "parlay": e.parlay_eligible, "score": None if e.score is None else _d(e.score.total, 2),
            "score_v": None if e.score is None else scoring.VERSION,
            "score_c": None if e.score is None or rejected else Jsonb(e.score.components),
            "stake": _d(st.units, 2), "stake_v": staking.VERSION, "stake_c": None if rejected else Jsonb(st.as_json()),
            "ctx_status": e.context.status,
            "ctx": Jsonb(e.context.as_json() | {"consensus": e.consensus} if not rejected
                         else {"status": e.context.status}),
            "review": None if e.context.review is None else int(e.context.review["id"]),
            "evidence": e.context.evidence_ids if not rejected else [],
            "hash": input_hash(e) if checkpoint is None and state is None else
            hashlib.sha256(f"{input_hash(e)}|{cp}|{state}".encode()).hexdigest()[:32],
            "code": code_version()})
        row = cur.fetchone()
    return None if row is None else int(row[0])


@dataclass
class DecideReport:
    candidates: int = 0
    evaluated: int = 0
    written: int = 0
    by_state: dict[str, int] = field(default_factory=dict)
    by_context: dict[str, int] = field(default_factory=dict)
    selected: int = 0
    parlays: int = 0


def decide(conn: psycopg.Connection[Any], *, at: datetime, horizon: timedelta = HORIZON,
           only: list[int] | None = None, write: bool = True) -> tuple[DecideReport, list[Evaluated]]:
    """One pass of the decision layer over the next ``horizon``. Idempotent; commits nothing itself."""
    report = DecideReport()
    cands = load_candidates(conn, at=at, horizon=horizon, only=only)
    report.candidates = len(cands)
    if not cands:
        return report, []
    fixtures = sorted({k[0] for k in cands})
    world = read_world(conn, fixtures, at=at)
    out = [evaluate(world, key, models) for key, models in cands.items()]
    correlate(out)
    report.evaluated = len(out)
    for e in out:
        report.by_state[e.state] = report.by_state.get(e.state, 0) + 1
        report.by_context[e.context.status] = report.by_context.get(e.context.status, 0) + 1
        if write and should_write(e, world.previous.get(e.key)) and store(conn, e, at=at) is not None:
            report.written += 1
    return report, out


# ── the picks of the day (daily-set-v6) and parlays, from approved decisions only ───────────────────────────────

RULE_V6 = "daily-set-v6"
MAX_PICKS = 5
MAX_PER_COMPETITION = 2
MAX_PARLAYS = 2
PARLAY_MIN_EV = 0.02

LATEST_DAY_SQL = """
SELECT DISTINCT ON (d.fixture_id, d.market_key, d.selection, d.line) d.*, c.id AS competition_id,
       f.home_team_id, f.away_team_id
  FROM intel.decisions d
  JOIN core.fixtures f ON f.id = d.fixture_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE d.kickoff_at >= %(start)s AND d.kickoff_at < %(end)s AND d.kickoff_at > %(at)s + interval '10 minutes'
   AND d.known_at <= %(at)s AND d.decision_version = %(version)s
 ORDER BY d.fixture_id, d.market_key, d.selection, d.line, d.known_at DESC, d.id DESC
"""


def select_day(conn: psycopg.Connection[Any], *, at: datetime, ready: bool) -> tuple[int, int]:
    """Add to today's PICKS DEL DÍA (up to five, one per match, at most two per competition, best score first) the
    approved selections whose newest decision is at most 30 minutes old, and up to two parlays of approved parlay
    candidates from different competitions. Frozen when chosen; never padded. Returns (picks, parlays) added."""
    if not ready:
        return 0, 0
    day = local_day(at)
    start, end = day_bounds(day)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(LATEST_DAY_SQL, {"start": start, "end": end, "at": at, "version": VERSION})
        latest = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT kind, rank, decision_ids FROM intel.day_selections WHERE day = %s AND rule_version = %s",
                    (day, RULE_V6))
        existing = [dict(r) for r in cur.fetchall()]
    taken_ids = [i for x in existing if x["kind"] == "pick" for i in x["decision_ids"]]
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT d.fixture_id, cs.competition_id FROM intel.decisions d "
                    "JOIN core.fixtures f ON f.id = d.fixture_id "
                    "JOIN core.competition_seasons cs ON cs.id = f.competition_season_id WHERE d.id = ANY(%s)",
                    (taken_ids or [0],))
        taken = [(int(r["fixture_id"]), int(r["competition_id"])) for r in cur.fetchall()]
    taken_fixtures = {fid for fid, _ in taken}
    comp_count: dict[int, int] = defaultdict(int)
    for _, comp in taken:
        comp_count[comp] += 1
    n_picks = sum(1 for x in existing if x["kind"] == "pick")
    fresh = [d for d in latest if d["state"] in ("APROBADO", "CANDIDATO_PARLAY", "PICK_PREMIUM")
             and at - d["known_at"] <= timedelta(minutes=30)]
    fresh.sort(key=lambda d: -float(d["score"] or 0))
    added = 0
    for d in fresh:
        if n_picks + added >= MAX_PICKS:
            break
        fid, comp = int(d["fixture_id"]), int(d["competition_id"])
        if fid in taken_fixtures or comp_count[comp] >= MAX_PER_COMPETITION:
            continue
        premium = bool(d["premium"])
        st = staking.stake_for("PICK_PREMIUM" if premium else "PICK_DEL_DIA", _num(d["p_cal"]), _num(d["odds"]),
                               _num(d["p_push"]) or 0.0)
        new_id = _copy_as(conn, d, at=at, state="PICK_DEL_DIA", stake=st)
        if new_id is None:
            continue
        with conn.cursor() as cur:
            cur.execute("INSERT INTO intel.day_selections (day, rule_version, kind, rank, decision_ids, selected_at, odds, "
                        "p_est, ev, stake_units, correlation, detail) VALUES (%s,%s,'pick',%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                        "ON CONFLICT DO NOTHING",
                        (day, RULE_V6, n_picks + added + 1, [new_id], at, d["odds"], d["p_cal"], d["ev_cal"],
                         _d(st.units, 2), Jsonb({}),
                         Jsonb({"score": None if d["score"] is None else float(d["score"]), "premium": premium,
                                "source_decision": int(d["id"]), "competition_id": comp})))
        taken_fixtures.add(fid)
        comp_count[comp] += 1
        added += 1
    parlays = _select_parlays(conn, day=day, at=at, latest=latest, existing=existing)
    return added, parlays


def _copy_as(conn: psycopg.Connection[Any], d: dict[str, Any], *, at: datetime, state: str,
             stake: staking.Stake) -> int | None:
    h = hashlib.sha256(f"{d['input_hash']}|selection|{state}|{at.date()}".encode()).hexdigest()[:32]
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO intel.decisions (decision_version, known_at, checkpoint, fixture_id, kickoff_at, market_key, "
            "selection, line, pick_id, model_name, model_version_id, odds, bookmaker_id, price_at, n_bookmakers, "
            "p_model, p_low, p_high, p_push, p_cal, calibrator_id, calibrator_role, p_market, ev_raw, edge_raw, ev_cal, "
            "edge_cal, filters, state, reasons, premium, parlay_eligible, score, score_version, score_components, "
            "stake_units, stake_version, stake_components, context_status, context, review_id, evidence_ids, input_hash, "
            "code_version) "
            "SELECT decision_version, %s, 'selection', fixture_id, kickoff_at, market_key, selection, line, pick_id, "
            "model_name, model_version_id, odds, bookmaker_id, price_at, n_bookmakers, p_model, p_low, p_high, p_push, "
            "p_cal, calibrator_id, calibrator_role, p_market, ev_raw, edge_raw, ev_cal, edge_cal, filters, %s, reasons, "
            "premium, parlay_eligible, score, score_version, score_components, %s, stake_version, %s, context_status, "
            "context || jsonb_build_object('selected_from', id), review_id, evidence_ids, %s, %s "
            "FROM intel.decisions WHERE id = %s ON CONFLICT DO NOTHING RETURNING id",
            (at, state, _d(stake.units, 2), Jsonb(stake.as_json()), h, code_version(), int(d["id"])))
        row = cur.fetchone()
    return None if row is None else int(row[0])


def _select_parlays(conn: psycopg.Connection[Any], *, day: date, at: datetime, latest: list[dict[str, Any]],
                    existing: list[dict[str, Any]]) -> int:
    from fbi.parlays.correlation import joint_probability

    have = sum(1 for x in existing if x["kind"] == "parlay")
    if have >= MAX_PARLAYS:
        return 0
    used = {i for x in existing if x["kind"] == "parlay" for i in x["decision_ids"]}
    legs = [d for d in latest if (d["parlay_eligible"] or d["state"] == "CANDIDATO_PARLAY")
            and d["state"] in ("APROBADO", "CANDIDATO_PARLAY", "PICK_PREMIUM")
            and at - d["known_at"] <= timedelta(minutes=30) and int(d["id"]) not in used]
    options: list[tuple[float, dict[str, Any], dict[str, Any], float, float]] = []
    for i, a in enumerate(legs):
        for b in legs[i + 1:]:
            if a["fixture_id"] == b["fixture_id"] or a["competition_id"] == b["competition_id"] or \
                    {a["home_team_id"], a["away_team_id"]} & {b["home_team_id"], b["away_team_id"]}:
                continue
            pa, pb = _num(a["p_cal"]) or 0, _num(b["p_cal"]) or 0
            joint = joint_probability([pa, pb], [])  # different competitions: no shared matchday to correlate
            odds = float(a["odds"]) * float(b["odds"])
            ev = joint * odds - 1
            if ev >= PARLAY_MIN_EV:
                options.append((ev, a, b, joint, odds))
    options.sort(key=lambda o: -o[0])
    added = 0
    taken: set[int] = set()
    for ev, a, b, joint, odds in options:
        if have + added >= MAX_PARLAYS:
            break
        if int(a["id"]) in taken or int(b["id"]) in taken:
            continue
        st = staking.stake_for("CANDIDATO_PARLAY", joint, odds, cap=staking.PARLAY_CAP)
        with conn.cursor() as cur:
            cur.execute("INSERT INTO intel.day_selections (day, rule_version, kind, rank, decision_ids, selected_at, odds, "
                        "p_est, ev, stake_units, correlation, detail) VALUES (%s,%s,'parlay',%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                        "ON CONFLICT DO NOTHING",
                        (day, RULE_V6, have + added + 1, [int(a["id"]), int(b["id"])], at, _d(odds, 3), _d(joint),
                         _d(ev), _d(st.units, 2),
                         Jsonb({"method": "independent across competitions (one leg per competition, no shared team)",
                                "pairs": []}),
                         Jsonb({"legs": [{"decision": int(x["id"]), "fixture": int(x["fixture_id"]),
                                          "market": x["market_key"], "selection": x["selection"],
                                          "line": str(x["line"]), "odds": float(x["odds"]), "p_cal": float(x["p_cal"])}
                                         for x in (a, b)], "risk": "dos patas, ambas aprobadas"})))
        taken |= {int(a["id"]), int(b["id"])}
        added += 1
    return added
