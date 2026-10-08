"""POST-MORTEM per selection (``pm-v2``): after its match, every selection PrediGol studied is asked ten questions,
from what was stored BEFORE kick-off and the result - and a loss gets a class.

Which selections: the picks of the day, the parlays' legs, every selection a language model reviewed, and every
reviewed selection of a match the AI worked on that day (it had a pass). Wins are studied as much as losses:
"rejected that would have won" and "approved that won" teach as much as the losses.

The ten questions (``answers``):

    expected        ¿Qué esperaba PrediGol?          the model, the market, the price, the decision
    happened        ¿Qué ocurrió?                    the score and how the selection settled
    model           ¿Falló el modelo?                the model far above the closing market, its log loss worse
    information     ¿Falló la información?           a report that proved wrong, an absence nobody reported
    ignored_signal  ¿Había una señal ignorada?       risks the review itself listed, and it approved anyway
    odds_moved      ¿La cuota se movió?              closing-line value of the price taken
    key_absence     ¿Existía una baja importante?    key players out on the chosen side, known before
    lineup_changed  ¿La alineación cambió?           confirmed after the last review, or a reported absentee started
    uncertainty     ¿La incertidumbre estaba subestimada?  an edge inside the model's own noise, approved
    variance        ¿Fue simplemente varianza?       none of the above: a fair price that lost

The class of a loss, the first that applies: DATA_ERROR (the data was not fit for models) - EXECUTION_ERROR (a stale
price, a kick-off changed after the selection) - CONTEXT_ERROR (the information failed, or a known key absence was
let through) - MARKET_ERROR (the market moved 3 % or more against the price taken: it knew something) - MODEL_ERROR
(the model 8 points or more above the closing market) - NORMAL_VARIANCE (the model close to the closing market, or
the price beat the close) - UNKNOWN (no closing price to judge by).

A post-mortem is written once (``ai.pick_postmortems``), never acted on: patterns over many become hypotheses
(``fbi.ai.patterns``), never a change. A short narrative, when a model is configured and the budget allows, is
written for the losses that matter most (the picks of the day first).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import psycopg
from psycopg.rows import dict_row, tuple_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from fbi.ai.config import AiSettings, Tier
from fbi.ai.memory import remember
from fbi.ai.postmortem import analyse as fixture_analysis
from fbi.ai.prompts import PICK_PM_SCHEMA, PICK_PM_SYSTEM, PICK_PM_VERSION
from fbi.ai.providers.base import JsonRequest, LlmProvider
from fbi.ai.review import side_of
from fbi.ai.usage import UsageLedger, call_json
from fbi.picks.settlement import market_outcome

VERSION = "pm-v2"
LOOKBACK = timedelta(days=7)
SETTLE_DELAY = timedelta(hours=3)
CLASSES = ("MODEL_ERROR", "CONTEXT_ERROR", "DATA_ERROR", "MARKET_ERROR", "EXECUTION_ERROR", "NORMAL_VARIANCE",
           "UNKNOWN")
CLV_AGAINST = -0.03
MODEL_GAP = 0.08
STALE_PRICE = timedelta(hours=3)
NOT_FIT = frozenset({"PRODUCT_ONLY", "INSUFFICIENT"})
MAX_NARRATIVES = 12
MAX_STRONG_NARRATIVES = 3
"""Narratives a run may pay for: the economical model for most, the intermediate one for the picks of the day."""

REVIEWED_SQL = """
SELECT DISTINCT ON (r.fixture_id, r.market_key, r.selection, r.line)
       r.fixture_id, r.market_key, r.selection, r.line, r.id AS review_id, r.decision, r.odds, r.bookmaker_id,
       r.p_model, r.p_low, r.p_market, r.reviewed_at, r.output, r.packet_id, r.pick_id
  FROM ai.pick_reviews r JOIN core.fixtures f ON f.id = r.fixture_id
 WHERE r.engine = 'combined' AND r.reviewed_at < f.kickoff_at
   AND f.kickoff_at >= %(since)s AND f.kickoff_at <= %(until)s AND f.status_group = 'finished'
 ORDER BY r.fixture_id, r.market_key, r.selection, r.line, r.reviewed_at DESC, r.id DESC
"""

ITEMS_SQL = """
SELECT 'daily_pick' AS role, i.fixture_id, i.market_key, i.selection, i.line, i.odds, i.bookmaker_id, i.p_model,
       i.p_low, i.p_market, i.price_at
  FROM picks.daily_set_items i JOIN core.fixtures f ON f.id = i.fixture_id
 WHERE f.kickoff_at >= %(since)s AND f.kickoff_at <= %(until)s AND f.status_group = 'finished'
UNION ALL
SELECT 'parlay_leg', l.fixture_id, l.market_key, l.selection, l.line, l.odds, l.bookmaker_id, l.p_model, l.p_low,
       l.p_market, l.price_at
  FROM picks.parlay_legs l JOIN core.fixtures f ON f.id = l.fixture_id
 WHERE f.kickoff_at >= %(since)s AND f.kickoff_at <= %(until)s AND f.status_group = 'finished'
"""

LLM_SQL = """
SELECT DISTINCT r.fixture_id, r.market_key, r.selection, r.line FROM ai.pick_reviews r JOIN core.fixtures f ON f.id = r.fixture_id
 WHERE r.engine = 'llm' AND r.status = 'ok' AND r.reviewed_at < f.kickoff_at
   AND f.kickoff_at >= %(since)s AND f.kickoff_at <= %(until)s
"""

PASSED_SQL = """
SELECT DISTINCT p.fixture_id FROM ai.fixture_passes p JOIN core.fixtures f ON f.id = p.fixture_id
 WHERE f.kickoff_at >= %(since)s AND f.kickoff_at <= %(until)s
"""

DONE_SQL = """
SELECT fixture_id, market_key, selection, line FROM ai.pick_postmortems
 WHERE version = %(version)s AND fixture_id = ANY(%(fixtures)s)
"""

FIXTURE_SQL = """
SELECT f.id, f.kickoff_at, th.name AS home, ta.name AS away, c.name AS competition, r.reg_goals_home, r.reg_goals_away
  FROM core.fixtures f JOIN core.fixture_results r ON r.fixture_id = f.id
  JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id JOIN core.competitions c ON c.id = cs.competition_id
 WHERE f.id = %(fixture)s AND r.reg_goals_home IS NOT NULL AND r.reg_goals_away IS NOT NULL
"""

CLOSE_P_SQL = """
SELECT m.p_fair FROM market.market_consensus m JOIN core.fixtures f ON f.id = m.fixture_id
 WHERE m.fixture_id = %(fixture)s AND m.market_key = %(market)s AND m.selection = %(selection)s AND m.line = %(line)s
   AND m.devig_method = 'shin' AND m.as_of < f.kickoff_at
 ORDER BY m.as_of DESC LIMIT 1
"""

CLOSE_ODDS_SQL = """
SELECT odds_decimal FROM market.final_prematch_odds
 WHERE fixture_id = %(fixture)s AND bookmaker_id = %(bookmaker)s AND market_key = %(market)s
   AND selection = %(selection)s AND line = %(line)s
"""

PACKET_SQL = "SELECT content, sources, as_of FROM ai.match_packets WHERE id = %(id)s"

LINEUP_AT_SQL = "SELECT min(fetched_at) FROM core.fixture_lineups WHERE fixture_id = %(fixture)s"


def _rows(conn: psycopg.Connection[Any], sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def _f(x: Any) -> float | None:
    return None if x is None else float(x)


def logloss(p: float, won: bool) -> float:
    q = min(max(p if won else 1 - p, 1e-6), 1.0)
    return -math.log(q)


@dataclass
class Facts:
    """What a post-mortem judges by: known before kick-off, and what happened."""

    settled: str
    decision: str | None
    p_model: float | None
    p_market: float | None
    p_close: float | None
    odds: float | None
    close_odds: float | None
    data_unfit: bool = False
    stale_price: bool = False
    kickoff_changed: bool = False
    information_failed: bool = False
    information: list[str] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)
    key_absence: list[str] = field(default_factory=list)
    lineup_changed: bool = False
    lineup_detail: str | None = None
    edge_in_noise: bool = False

    @property
    def won(self) -> bool:
        return self.settled in ("win", "half_win")

    @property
    def lost(self) -> bool:
        return self.settled in ("loss", "half_loss")

    @property
    def clv(self) -> float | None:
        if self.odds is None or not self.close_odds:
            return None
        return round(self.odds / self.close_odds - 1, 4)


def classify(f: Facts) -> str | None:
    """The class of a loss (None for anything else), the first that applies."""
    if not f.lost:
        return None
    if f.data_unfit:
        return "DATA_ERROR"
    if f.stale_price or f.kickoff_changed:
        return "EXECUTION_ERROR"
    if f.information_failed or (f.key_absence and f.decision == "APPROVE"):
        return "CONTEXT_ERROR"
    clv = f.clv
    moved_against = (clv is not None and clv <= CLV_AGAINST) or (
        f.p_close is not None and f.p_market is not None and f.p_close <= f.p_market + CLV_AGAINST)
    if moved_against:
        return "MARKET_ERROR"
    if f.p_close is not None and f.p_model is not None and f.p_model - f.p_close >= MODEL_GAP:
        return "MODEL_ERROR"
    if f.p_close is not None or (clv is not None and clv >= 0):
        return "NORMAL_VARIANCE"
    return "UNKNOWN"


def verdict_of(f: Facts) -> str:
    if not (f.won or f.lost):
        return "push"
    d = f.decision
    if d == "APPROVE":
        return "approved_won" if f.won else "approved_lost"
    if d == "DOWNGRADE":
        return "caution_won" if f.won else "caution_lost"
    if d == "REJECT":
        return "rejected_would_have_won" if f.won else "rejected_correctly"
    return "unreviewed_won" if f.won else "unreviewed_lost"


def _yes(x: bool | None) -> str:
    return "sin datos" if x is None else "sí" if x else "no"


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{100 * x:.1f} %"


def answers(f: Facts, cls: str | None, *, score: tuple[int, int], label: str) -> dict[str, Any]:
    clv = f.clv
    ll_model = None if f.p_model is None or not (f.won or f.lost) else round(logloss(f.p_model, f.won), 4)
    ll_close = None if f.p_close is None or not (f.won or f.lost) else round(logloss(f.p_close, f.won), 4)
    model_failed = None if f.p_close is None or f.p_model is None else (
        f.lost and f.p_model - f.p_close >= MODEL_GAP)
    return {
        "expected": {"answer": label, "detail": f"PrediGol {_pct(f.p_model)} · mercado {_pct(f.p_market)} · cuota "
                     f"{'—' if f.odds is None else f'{f.odds:.2f}'} · decisión {f.decision or 'sin revisión'}",
                     "data": {"p_model": f.p_model, "p_market": f.p_market, "odds": f.odds, "decision": f.decision}},
        "happened": {"answer": f.settled, "detail": f"{score[0]}-{score[1]}: la selección {f.settled}",
                     "data": {"score": list(score)}},
        "model": {"answer": _yes(model_failed),
                  "detail": f"modelo {_pct(f.p_model)} frente al cierre {_pct(f.p_close)}; log loss modelo "
                            f"{ll_model} vs cierre {ll_close}",
                  "data": {"p_close": f.p_close, "logloss_model": ll_model, "logloss_close": ll_close}},
        "information": {"answer": _yes(f.information_failed), "detail": "; ".join(f.information) or "nada falló",
                        "data": {"items": f.information}},
        "ignored_signal": {"answer": _yes(bool(f.ignored) and f.decision == "APPROVE"),
                           "detail": ", ".join(f.ignored) or "ninguna", "data": {"signals": f.ignored}},
        "odds_moved": {"answer": "sin datos" if clv is None else "en contra" if clv <= CLV_AGAINST
                       else "a favor" if clv >= -CLV_AGAINST else "estable",
                       "detail": f"CLV {'—' if clv is None else f'{100 * clv:+.1f} %'} (cuota tomada "
                                 f"{f.odds} · cierre {f.close_odds})", "data": {"clv": clv, "close_odds": f.close_odds}},
        "key_absence": {"answer": _yes(bool(f.key_absence)), "detail": ", ".join(f.key_absence) or "ninguna",
                        "data": {"players": f.key_absence}},
        "lineup_changed": {"answer": _yes(f.lineup_changed), "detail": f.lineup_detail or "sin cambios relevantes",
                           "data": {}},
        "uncertainty": {"answer": _yes(f.edge_in_noise and f.decision == "APPROVE"),
                        "detail": "la ventaja estaba dentro del ruido del modelo" if f.edge_in_noise
                        else "la ventaja superaba el ruido del modelo", "data": {"edge_in_noise": f.edge_in_noise}},
        "variance": {"answer": _yes(cls == "NORMAL_VARIANCE") if f.lost else "no aplica",
                     "detail": (f"con el cierre en {_pct(f.p_close)}, perder tenía {_pct(1 - f.p_close)} de "
                                "probabilidad") if f.p_close is not None and f.lost else "—", "data": {}},
    }


class NarrativeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=3, max_length=900)
    agrees_with_class: bool
    lessons: list[str] = Field(default_factory=list, max_length=2)


@dataclass
class PickPostmortemReport:
    studied: int = 0
    losses: int = 0
    wins: int = 0
    narratives: int = 0
    memory_events: int = 0
    by_class: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def _facts(conn: psycopg.Connection[Any], s: dict[str, Any], *, home: int, away: int, kickoff: datetime,
           findings: dict[str, Any] | None) -> Facts:
    line = Decimal(s["line"])
    try:
        settled = str(market_outcome(s["market_key"], s["selection"], line, home, away).value)
    except ValueError:
        settled = "unknown"
    close_p = _rows(conn, CLOSE_P_SQL, {"fixture": s["fixture_id"], "market": s["market_key"],
                                        "selection": s["selection"], "line": line})
    close_odds = None
    if s.get("bookmaker_id") is not None:
        c = _rows(conn, CLOSE_ODDS_SQL, {"fixture": s["fixture_id"], "bookmaker": s["bookmaker_id"],
                                         "market": s["market_key"], "selection": s["selection"], "line": line})
        close_odds = None if not c else float(c[0]["odds_decimal"])
    f = Facts(settled=settled, decision=s.get("decision"), p_model=_f(s.get("p_model")), p_market=_f(s.get("p_market")),
              p_close=None if not close_p else float(close_p[0]["p_fair"]), odds=_f(s.get("odds")),
              close_odds=close_odds)
    output = s.get("output") or {}
    codes = [c.get("code") for g in ("negative_evidence", "uncertainties", "contradictions")
             for c in output.get(g, []) if c.get("code")]
    f.ignored = sorted(set(codes) - {"lineups_confirmed"})
    f.edge_in_noise = "edge_within_noise" in codes
    f.kickoff_changed = "kickoff_changed" in codes
    side = side_of(s["market_key"], s["selection"])
    opp = "away" if side == "home" else "home" if side == "away" else None
    content: dict[str, Any] = {}
    sources: list[dict[str, Any]] = []
    review_at: datetime | None = s.get("reviewed_at")
    if s.get("packet_id"):
        rows = _rows(conn, PACKET_SQL, {"id": s["packet_id"]})
        if rows:
            content, sources = dict(rows[0]["content"] or {}), list(rows[0]["sources"] or [])
    quality = ((content.get("quality") or {}).get("competition_score") or {}).get("class")
    validation = ((content.get("quality") or {}).get("fixture_validation") or {}).get("state")
    f.data_unfit = quality in NOT_FIT or validation == "QUARANTINED"
    price_at: datetime | None = s.get("price_at")
    if price_at is None:
        market_as_of = next((x.get("as_of") for x in sources if x.get("block") == "market"), None)
        price_at = None if not market_as_of else datetime.fromisoformat(str(market_as_of))
    moment = review_at or s.get("selected_at")
    if price_at is not None and moment is not None and moment - price_at > STALE_PRICE:
        f.stale_price = True
    absences = content.get("absences") or {}
    sides = [side] if side in ("home", "away") else ["home", "away"]
    for sd in sides:
        for p in (absences.get(sd) or {}).get("players", []):
            if p.get("key") and not str(p.get("type") or "").startswith("Quest"):
                f.key_absence.append(f"{p.get('name')} ({'local' if sd == 'home' else 'visitante'})")
    for e in (findings or {}).get("evidence", []):
        # a report that proved wrong hurts the pick when it made the opponent look weaker (or any, for a total/draw)
        if e.get("verdict") == "wrong" and (opp is None or e.get("side") in (opp, None)):
            f.information.append(f"reportado fuera y fue titular ({e.get('tier')}): {str(e.get('claim', ''))[:80]}")
    for m in (findings or {}).get("missing_information", []):
        if side not in ("home", "away") or m.get("side") == side:
            f.information.append(f"titular habitual ausente sin reporte ({'local' if m.get('side') == 'home' else 'visitante'}"
                                 f", jugador {m.get('player_id')})")
    f.information_failed = bool(f.information)
    lineup_at = _rows(conn, LINEUP_AT_SQL, {"fixture": s["fixture_id"]})
    first_lineup = lineup_at[0]["min"] if lineup_at else None
    if first_lineup is not None and first_lineup < kickoff and not output.get("lineups_seen") \
            and review_at is not None and first_lineup > review_at:
        f.lineup_changed = True
        f.lineup_detail = "las alineaciones se confirmaron después de la última revisión"
    if any(e.get("verdict") == "wrong" for e in (findings or {}).get("evidence", [])):
        f.lineup_changed = True
        f.lineup_detail = (f.lineup_detail + "; " if f.lineup_detail else "") + \
            "un jugador reportado fuera fue titular"
    return f


def run_pick_postmortems(conn: psycopg.Connection[Any], *, at: datetime, settings: AiSettings | None = None,
                         ledger: UsageLedger | None = None, provider: tuple[LlmProvider, str] | None = None,
                         transport: httpx.BaseTransport | None = None, limit: int = 400) -> PickPostmortemReport:
    settings = settings or AiSettings.from_env()
    report = PickPostmortemReport()
    window = {"since": at - LOOKBACK, "until": at - SETTLE_DELAY}
    reviewed = {(int(r["fixture_id"]), r["market_key"], r["selection"], Decimal(r["line"])): r
                for r in _rows(conn, REVIEWED_SQL, window)}
    roles: dict[tuple[int, str, str, Decimal], set[str]] = {}
    items: dict[tuple[int, str, str, Decimal], dict[str, Any]] = {}
    for r in _rows(conn, ITEMS_SQL, window):
        key = (int(r["fixture_id"]), r["market_key"], r["selection"], Decimal(r["line"]))
        roles.setdefault(key, set()).add(r["role"])
        items.setdefault(key, r)
    for r in _rows(conn, LLM_SQL, window):
        roles.setdefault((int(r["fixture_id"]), r["market_key"], r["selection"], Decimal(r["line"])), set()).add("llm")
    passed = {int(r["fixture_id"]) for r in _rows(conn, PASSED_SQL, window)}
    wanted: dict[tuple[int, str, str, Decimal], dict[str, Any]] = {}
    for key, r in reviewed.items():
        if key in roles or key[0] in passed:
            wanted[key] = dict(r)
    for key, r in items.items():
        if key not in wanted:
            wanted[key] = dict(r) | {"decision": None, "review_id": None, "output": {}, "packet_id": None,
                                     "reviewed_at": None}
    if not wanted:
        return report
    done = {(int(r["fixture_id"]), r["market_key"], r["selection"], Decimal(r["line"]))
            for r in _rows(conn, DONE_SQL, {"version": VERSION, "fixtures": sorted({k[0] for k in wanted})})}
    todo = sorted((k for k in wanted if k not in done), key=lambda k: (k[0], k[1], k[2], k[3]))[:limit]
    llm_ok = settings.llm_configured or provider is not None
    narratives_left, strong_left = (MAX_NARRATIVES, MAX_STRONG_NARRATIVES) if llm_ok else (0, 0)
    fixtures: dict[int, dict[str, Any] | None] = {}
    findings: dict[int, dict[str, Any] | None] = {}
    for key in todo:
        fid = key[0]
        s = wanted[key]
        try:
            if fid not in fixtures:
                rows = _rows(conn, FIXTURE_SQL, {"fixture": fid})
                fixtures[fid] = rows[0] if rows else None
                got = fixture_analysis(conn, fid) if rows else None
                findings[fid] = None if got is None else got[2]
            fx = fixtures[fid]
            if fx is None:
                continue
            home, away = int(fx["reg_goals_home"]), int(fx["reg_goals_away"])
            facts = _facts(conn, s, home=home, away=away, kickoff=fx["kickoff_at"], findings=findings.get(fid))
            if facts.settled == "unknown":
                continue
            cls = classify(facts)
            verdict = verdict_of(facts)
            sel_roles = sorted(roles.get(key, set()) | ({"reviewed"} if s.get("review_id") else set())
                               | ({"rejected"} if s.get("decision") == "REJECT" else set()))
            label = f"{fx['home']} - {fx['away']} · {key[1]} {key[2]}" + (f" {key[3]}" if key[3] else "")
            ans = answers(facts, cls, score=(home, away), label=label)
            narrative, usage_ids = None, []
            important = (facts.lost and s.get("decision") in ("APPROVE", "DOWNGRADE", None)) \
                or verdict == "rejected_would_have_won"
            strong = "daily_pick" in sel_roles and facts.lost
            if important and narratives_left > 0:
                tier: Tier = "analysis" if strong and strong_left > 0 else "bulk"
                body = json.dumps({"selection": label, "verdict": verdict, "class": cls, "answers": ans,
                                   "review": {k: (s.get("output") or {}).get(k) for k in
                                              ("reason", "positive_evidence", "negative_evidence", "uncertainties")},
                                   "roles": sel_roles}, ensure_ascii=False, default=str)
                call = call_json(conn, settings, tier=tier, purpose="postmortem",
                                 request=JsonRequest(PICK_PM_SYSTEM, body, PICK_PM_SCHEMA, "submit_postmortem",
                                                     max_tokens=3000), at=at, prompt_version=PICK_PM_VERSION,
                                 input_hash=f"{VERSION}:{fid}:{key[1]}:{key[2]}:{key[3]}", fixture_id=fid,
                                 ledger=ledger, transport=transport, provider=provider)
                if call.usage_id:
                    usage_ids.append(call.usage_id)
                if call.result is not None:
                    try:
                        parsed = NarrativeOut.model_validate(call.result.data)
                        narrative = parsed.summary + ("" if parsed.agrees_with_class else
                                                      " (el revisor no comparte la clase del servidor)") + \
                            ("\n- " + "\n- ".join(parsed.lessons) if parsed.lessons else "")
                        report.narratives += 1
                        narratives_left -= 1
                        if tier == "analysis":
                            strong_left -= 1
                    except ValidationError:
                        narrative = None
            evidence = {"review_id": s.get("review_id"), "packet_id": s.get("packet_id"),
                        "findings": (findings.get(fid) or {}).get("match_forecast"), "roles": sel_roles,
                        "competition": fx["competition"], "kickoff_at": fx["kickoff_at"].isoformat()}
            with conn.cursor(row_factory=tuple_row) as cur:
                cur.execute(
                    "INSERT INTO ai.pick_postmortems (fixture_id, market_key, selection, line, created_at, version, "
                    "roles, decision, review_id, settled, verdict, classification, odds, close_odds, clv, p_model, "
                    "p_market, answers, evidence, narrative, usage_ids) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
                    "%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id",
                    (fid, key[1], key[2], key[3], at, VERSION, sel_roles, s.get("decision"), s.get("review_id"),
                     facts.settled, verdict, cls, facts.odds, facts.close_odds, facts.clv, facts.p_model,
                     facts.p_market, Jsonb(ans), Jsonb(evidence), narrative, usage_ids))
                row = cur.fetchone()
            if row is not None and remember(
                    conn, at=at, kind="pick_postmortem", entity_type="market",
                    entity_id=f"{key[1]}:{key[2]}:{key[3]}", version=VERSION, fixture_id=fid,
                    hypothesis=f"{verdict} {label}", result=cls or verdict,
                    evidence={"postmortem_id": int(row[0]), "verdict": verdict, "class": cls, "clv": facts.clv,
                              "p_model": facts.p_model, "p_close": facts.p_close, "roles": sel_roles,
                              "competition": fx["competition"], "signals": facts.ignored,
                              "odds": facts.odds, "result": facts.settled},
                    dedup_key=f"pm2:{fid}:{key[1]}:{key[2]}:{key[3]}"):
                report.memory_events += 1
            report.studied += 1
            report.losses += int(facts.lost)
            report.wins += int(facts.won)
            if cls:
                report.by_class[cls] = report.by_class.get(cls, 0) + 1
            conn.commit()
        except Exception as exc:
            conn.rollback()
            report.errors.append(f"{fid}: {type(exc).__name__}: {exc}"[:200])
    return report
