"""POST-MORTEM: after a match, what was expected, what happened, and what that says - written down, never
acted on.

For every finished match the AI reviewed (rule ``pm-v1``):

* the outcome: the regulation score, who started (when the line-ups are stored);
* per reviewed selection: the model's and the market's probability, the review's decision, how it settled,
  each forecast's log loss on it, and the closing-line value of the price taken (against the provider's
  final pre-match price of the same bookmaker, when it was read);
* the evidence checked against what happened: a player reported OUT who started (a context error, by the
  source's tier), reported out and absent (confirmed), and key regulars absent from the starting line-up
  without any report (missing information);
* the match's 1X2 forecast: the model's against the market's closing consensus (log loss), a model failure
  or success when the difference is large.

Each of these becomes memory events (``ai.memory_events``); the narrative, when a model is configured and
the budget allows, is a short summary for the owner. Losses are studied as much as wins, but a single
match never proposes a change: patterns over many matches do (``fbi.ai.patterns``), and only as
hypotheses.
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

from fbi.ai.config import AiSettings
from fbi.ai.memory import remember
from fbi.ai.prompts import POSTMORTEM_SCHEMA, POSTMORTEM_SYSTEM, POSTMORTEM_VERSION
from fbi.ai.providers.base import JsonRequest, LlmProvider
from fbi.ai.usage import UsageLedger, call_json
from fbi.picks.settlement import Status, market_outcome

VERSION = "pm-v1"
LOOKBACK = timedelta(days=7)
SETTLE_DELAY = timedelta(hours=3)
LARGE_LOGLOSS_DIFF = 0.25
MAX_NARRATIVES_PER_RUN = 10

DUE_SQL = """
SELECT DISTINCT f.id, f.kickoff_at
  FROM core.fixtures f JOIN core.fixture_results r ON r.fixture_id = f.id
 WHERE f.kickoff_at >= %(since)s AND f.kickoff_at <= %(until)s AND f.status_group = 'finished'
   AND r.reg_goals_home IS NOT NULL AND r.reg_goals_away IS NOT NULL
   AND EXISTS (SELECT 1 FROM ai.pick_reviews pr WHERE pr.fixture_id = f.id)
   AND NOT EXISTS (SELECT 1 FROM ai.postmortems pm WHERE pm.fixture_id = f.id AND pm.version = %(version)s)
 ORDER BY f.kickoff_at
 LIMIT %(limit)s
"""

FIXTURE_SQL = """
SELECT f.id, f.kickoff_at, f.home_team_id, f.away_team_id, th.name AS home_name, ta.name AS away_name,
       th.provider_team_id AS home_provider_id, ta.provider_team_id AS away_provider_id, cs.season,
       c.id AS competition_id, c.name AS competition, c.provider_league_id,
       r.reg_goals_home, r.reg_goals_away
  FROM core.fixtures f JOIN core.fixture_results r ON r.fixture_id = f.id
  JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id JOIN core.competitions c ON c.id = cs.competition_id
 WHERE f.id = %(fixture)s
"""

REVIEWS_SQL = """
SELECT DISTINCT ON (r.market_key, r.selection, r.line)
       r.id, r.market_key, r.selection, r.line, r.odds, r.bookmaker_id, r.p_model, r.p_market, r.decision,
       r.confidence, r.engine_version, r.output, r.evidence_ids, r.reviewed_at
  FROM ai.pick_reviews r JOIN core.fixtures f ON f.id = r.fixture_id
 WHERE r.fixture_id = %(fixture)s AND r.engine = 'combined' AND r.reviewed_at < f.kickoff_at
 ORDER BY r.market_key, r.selection, r.line, r.reviewed_at DESC, r.id DESC
"""

CLOSE_SQL = """
SELECT odds_decimal FROM market.final_prematch_odds
 WHERE fixture_id = %(fixture)s AND bookmaker_id = %(bookmaker)s AND market_key = %(market)s
   AND selection = %(selection)s AND line = %(line)s
"""

LINEUP_SQL = """
SELECT lp.team_side, lp.provider_player_id, lp.player_name, lp.is_starter
  FROM core.fixture_lineup_players lp WHERE lp.fixture_id = %(fixture)s
"""

EVIDENCE_SQL = """
SELECT e.id, e.team_id, e.provider_player_id, e.kind, e.origin, e.source_tier, e.status, e.attributes, e.claim
  FROM ai.evidence e JOIN core.fixtures f ON f.id = e.fixture_id
 WHERE e.fixture_id = %(fixture)s AND e.retrieved_at < f.kickoff_at
   AND e.kind IN ('injury', 'suspension', 'doubtful')
"""

CLOSING_1X2_SQL = """
SELECT DISTINCT ON (m.selection) m.selection, m.p_fair
  FROM market.market_consensus m JOIN core.fixtures f ON f.id = m.fixture_id
 WHERE m.fixture_id = %(fixture)s AND m.market_key = '1X2' AND m.devig_method = 'shin' AND m.as_of < f.kickoff_at
 ORDER BY m.selection, m.as_of DESC
"""

MODEL_1X2_SQL = """
WITH newest AS (
    SELECT p.model_version_id, p.data_cutoff_ts FROM models.predictions p
      JOIN models.model_versions v ON v.id = p.model_version_id JOIN models.model_registry m ON m.id = v.model_id
      JOIN core.fixtures f ON f.id = p.fixture_id
     WHERE p.fixture_id = %(fixture)s AND p.backtest_session_id IS NULL AND m.name = %(model)s
       AND p.data_cutoff_ts < f.kickoff_at AND p.market_key = '1X2'
     ORDER BY p.data_cutoff_ts DESC LIMIT 1
)
SELECT p.selection, p.p_calibrated FROM models.predictions p JOIN newest n ON n.model_version_id = p.model_version_id
   AND n.data_cutoff_ts = p.data_cutoff_ts
 WHERE p.fixture_id = %(fixture)s AND p.market_key = '1X2' AND p.backtest_session_id IS NULL
"""

REGULARS_SQL = """
SELECT DISTINCT ON (s.provider_player_id) s.provider_player_id, s.minutes
  FROM core.player_season_stats s
 WHERE s.provider_team_id = %(team)s AND s.season = %(season)s AND s.provider_league_id = %(league)s
 ORDER BY s.provider_player_id, s.observed_at DESC
"""


def _rows(conn: psycopg.Connection[Any], sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def logloss(p: float, won: bool) -> float:
    q = min(max(p if won else 1 - p, 1e-6), 1.0)
    return -math.log(q)


class NarrativeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=3, max_length=900)
    lessons: list[str] = Field(default_factory=list, max_length=3)


@dataclass
class PostmortemReport:
    fixtures: int = 0
    memory_events: int = 0
    narratives: int = 0
    context_errors: int = 0
    errors: list[str] = field(default_factory=list)


def _settle(market: str, selection: str, line: Decimal, home: int, away: int) -> str:
    try:
        return str(market_outcome(market, selection, line, home, away).value)
    except ValueError:
        return "unknown"


def analyse(conn: psycopg.Connection[Any], fixture_id: int) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    """(outcome, expected, findings) of one finished match - pure reads."""
    fx = _rows(conn, FIXTURE_SQL, {"fixture": fixture_id})
    if not fx:
        return None
    f = fx[0]
    home, away = int(f["reg_goals_home"]), int(f["reg_goals_away"])
    lineup = _rows(conn, LINEUP_SQL, {"fixture": fixture_id})
    starters = {(r["team_side"], int(r["provider_player_id"])) for r in lineup if r["is_starter"] and r["provider_player_id"]}
    in_squad = {(r["team_side"], int(r["provider_player_id"])) for r in lineup if r["provider_player_id"]}
    outcome = {"score": [home, away], "result": "Home" if home > away else "Draw" if home == away else "Away",
               "total_goals": home + away, "btts": home > 0 and away > 0, "lineups_known": bool(lineup)}

    expected: dict[str, Any] = {"selections": []}
    for r in _rows(conn, REVIEWS_SQL, {"fixture": fixture_id}):
        line = Decimal(r["line"])
        status = _settle(r["market_key"], r["selection"], line, home, away)
        won = status in ("win", "half_win")
        close = None
        if r["bookmaker_id"] is not None:
            c = _rows(conn, CLOSE_SQL, {"fixture": fixture_id, "bookmaker": r["bookmaker_id"], "market": r["market_key"],
                                        "selection": r["selection"], "line": line})
            close = None if not c else float(c[0]["odds_decimal"])
        odds = None if r["odds"] is None else float(r["odds"])
        entry = {"review_id": int(r["id"]), "market": r["market_key"], "selection": r["selection"], "line": str(line),
                 "decision": r["decision"], "confidence": float(r["confidence"]), "odds": odds,
                 "p_model": None if r["p_model"] is None else float(r["p_model"]),
                 "p_market": None if r["p_market"] is None else float(r["p_market"]), "settled": status,
                 "close_odds": close, "clv": None if (odds is None or not close) else round(odds / close - 1, 4),
                 "signals": [c.get("code") for g in ("negative_evidence", "uncertainties", "contradictions")
                             for c in (r["output"] or {}).get(g, []) if c.get("code")]}
        if status in ("win", "loss") and entry["p_model"] is not None and entry["p_market"] is not None:
            entry["logloss_model"] = round(logloss(entry["p_model"], won), 4)
            entry["logloss_market"] = round(logloss(entry["p_market"], won), 4)
        expected["selections"].append(entry)

    findings: dict[str, Any] = {"evidence": [], "missing_information": [], "match_forecast": None}
    side_of_team = {f["home_team_id"]: "home", f["away_team_id"]: "away"}
    for e in _rows(conn, EVIDENCE_SQL, {"fixture": fixture_id}):
        side = side_of_team.get(e["team_id"])
        pid = e["provider_player_id"]
        if side is None or pid is None or not lineup:
            continue
        assertion = (e["attributes"] or {}).get("assertion")
        started = (side, int(pid)) in starters
        verdict = ("wrong" if started and assertion == "out" else
                   "right" if not started and assertion == "out" else
                   "started" if started else "did_not_start")
        findings["evidence"].append({"evidence_id": int(e["id"]), "side": side, "tier": e["source_tier"],
                                     "origin": e["origin"],
                                     "kind": e["kind"], "status": e["status"], "assertion": assertion, "verdict": verdict,
                                     "claim": e["claim"][:160]})
    reported = {(side_of_team.get(e["team_id"]), e["provider_player_id"]) for e in
                _rows(conn, EVIDENCE_SQL, {"fixture": fixture_id})}
    if lineup:
        for side, provider_team in (("home", f["home_provider_id"]), ("away", f["away_provider_id"])):
            regs = _rows(conn, REGULARS_SQL, {"team": provider_team, "season": f["season"],
                                              "league": f["provider_league_id"]})
            regs = sorted(regs, key=lambda r: -(r["minutes"] or 0))[:11]
            top = max((r["minutes"] or 0) for r in regs) if regs else 0
            for r in regs:
                pid = int(r["provider_player_id"])
                if top and (r["minutes"] or 0) >= 0.6 * top and (side, pid) not in starters \
                        and (side, pid) not in reported and (side, pid) not in in_squad:
                    findings["missing_information"].append({"side": side, "player_id": pid,
                                                            "minutes": r["minutes"]})
    market = {r["selection"]: float(r["p_fair"]) for r in _rows(conn, CLOSING_1X2_SQL, {"fixture": fixture_id})}
    model = {r["selection"]: float(r["p_calibrated"]) for r in
             _rows(conn, MODEL_1X2_SQL, {"fixture": fixture_id, "model": "dixon_coles"})}
    actual = outcome["result"]
    if actual in market and actual in model:
        diff = logloss(model[actual], True) - logloss(market[actual], True)
        findings["match_forecast"] = {"model": "dixon_coles", "p_model_actual": round(model[actual], 4),
                                      "p_market_actual": round(market[actual], 4), "logloss_diff": round(diff, 4),
                                      "closer": "model" if diff < 0 else "market"}
    return outcome, expected, findings


def write_memory(conn: psycopg.Connection[Any], fixture_id: int, outcome: dict[str, Any], expected: dict[str, Any],
                 findings: dict[str, Any], *, at: datetime) -> tuple[int, int]:
    n = errors = 0
    key = f"pm:{VERSION}:{fixture_id}"
    if remember(conn, at=at, kind="match_result", entity_type="fixture", entity_id=str(fixture_id), version=VERSION,
                fixture_id=fixture_id, evidence=outcome, result=f"{outcome['score'][0]}-{outcome['score'][1]}",
                dedup_key=f"{key}:result"):
        n += 1
    for s in expected["selections"]:
        verdict = None
        if s["settled"] in ("win", "loss"):
            good = (s["decision"] == "REJECT") == (s["settled"] == "loss")
            verdict = "right" if good else "wrong"
        if remember(conn, at=at, kind="pick_result", entity_type="fixture", entity_id=str(fixture_id), version=VERSION,
                    fixture_id=fixture_id, hypothesis=f"{s['decision']} {s['market']} {s['selection']} {s['line']}",
                    evidence=s, result=s["settled"], confidence=s["confidence"],
                    dedup_key=f"{key}:pick:{s['market']}:{s['selection']}:{s['line']}"):
            n += 1
        if verdict is not None and s["decision"] in ("APPROVE", "REJECT", "DOWNGRADE") and remember(
                conn, at=at, kind="review_quality", entity_type="reviewer", entity_id="combined", version=VERSION,
                fixture_id=fixture_id, hypothesis=f"{s['decision']} was the right call", evidence=s, result=verdict,
                dedup_key=f"{key}:rq:{s['market']}:{s['selection']}:{s['line']}"):
            n += 1
    for e in findings["evidence"]:
        if e["verdict"] == "wrong":
            errors += 1
            if remember(conn, at=at, kind="context_error", entity_type="source", entity_id=str(e["tier"]),
                        version=VERSION, fixture_id=fixture_id, hypothesis=e["claim"], evidence=e,
                        result="the player started", dedup_key=f"{key}:ce:{e['evidence_id']}"):
                n += 1
        elif e["verdict"] == "right":
            if remember(conn, at=at, kind="injury_signal", entity_type="source", entity_id=str(e["tier"]),
                        version=VERSION, fixture_id=fixture_id, hypothesis=e["claim"], evidence=e,
                        result="confirmed by the line-up", dedup_key=f"{key}:is:{e['evidence_id']}"):
                n += 1
    for m in findings["missing_information"]:
        if remember(conn, at=at, kind="news_signal", entity_type="player", entity_id=str(m["player_id"]),
                    version=VERSION, fixture_id=fixture_id, hypothesis="a regular starter was missing without any "
                    "report", evidence=m, result="unreported absence", dedup_key=f"{key}:mi:{m['side']}:{m['player_id']}"):
            n += 1
    mf = findings.get("match_forecast")
    if mf is not None and abs(mf["logloss_diff"]) >= LARGE_LOGLOSS_DIFF:
        kind = "model_failure" if mf["logloss_diff"] > 0 else "model_success"
        if remember(conn, at=at, kind=kind, entity_type="model", entity_id=mf["model"], version=VERSION,  # type: ignore[arg-type]
                    fixture_id=fixture_id, evidence=mf, result=f"log loss {mf['logloss_diff']:+.3f} vs the close",
                    dedup_key=f"{key}:mf"):
            n += 1
    return n, errors


def run_postmortems(conn: psycopg.Connection[Any], *, at: datetime, settings: AiSettings | None = None,
                    ledger: UsageLedger | None = None, limit: int = 200,
                    provider: tuple[LlmProvider, str] | None = None,
                    transport: httpx.BaseTransport | None = None) -> PostmortemReport:
    settings = settings or AiSettings.from_env()
    report = PostmortemReport()
    due = _rows(conn, DUE_SQL, {"since": at - LOOKBACK, "until": at - SETTLE_DELAY, "version": VERSION, "limit": limit})
    narratives_left = MAX_NARRATIVES_PER_RUN if (settings.llm_configured or provider is not None) else 0
    for row in due:
        fid = int(row["id"])
        try:
            got = analyse(conn, fid)
            if got is None:
                continue
            outcome, expected, findings = got
            narrative, usage_ids = None, []
            decisive = [s for s in expected["selections"] if s["decision"] in ("APPROVE", "REJECT")]
            if narratives_left > 0 and decisive:
                body = json.dumps({"outcome": outcome, "expected": expected, "findings": findings}, default=str,
                                  ensure_ascii=False)
                call = call_json(conn, settings, tier="bulk", purpose="postmortem",
                                 request=JsonRequest(POSTMORTEM_SYSTEM, body, POSTMORTEM_SCHEMA, "submit_postmortem",
                                                     max_tokens=3000), at=at, prompt_version=POSTMORTEM_VERSION,
                                 input_hash=str(fid), fixture_id=fid, ledger=ledger, transport=transport,
                                 provider=provider)
                if call.usage_id:
                    usage_ids.append(call.usage_id)
                if call.result is not None:
                    try:
                        parsed = NarrativeOut.model_validate(call.result.data)
                        narrative = parsed.summary + ("\n- " + "\n- ".join(parsed.lessons) if parsed.lessons else "")
                        narratives_left -= 1
                        report.narratives += 1
                    except ValidationError:
                        narrative = None
            with conn.cursor(row_factory=tuple_row) as cur:
                cur.execute("INSERT INTO ai.postmortems (fixture_id, created_at, version, outcome, expected, findings, "
                            "narrative, usage_ids) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                            (fid, at, VERSION, Jsonb(outcome), Jsonb(expected), Jsonb(findings), narrative, usage_ids))
            n, errors = write_memory(conn, fid, outcome, expected, findings, at=at)
            report.memory_events += n
            report.context_errors += errors
            report.fixtures += 1
            conn.commit()
        except Exception as exc:
            conn.rollback()
            report.errors.append(f"{fid}: {type(exc).__name__}: {exc}"[:200])
    return report


__all__ = ["VERSION", "Status", "analyse", "run_postmortems", "write_memory"]
