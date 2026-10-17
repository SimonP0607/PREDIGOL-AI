"""PrediGol Intelligence for the Admin Console: the day, the decisions and their full record, the match dossier and
its narrative, calibration and the gates, the memory, the daily learning reports, the market registry, the runs and
the leakage audit, and what it all cost. Reading only."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from fbi.ai.calendar import day_bounds, day_start, local_day, month_start
from fbi.ai.config import AiSettings
from fbi.api.envelope import Envelope, ok
from fbi.api.errors import ApiError
from fbi.api.repositories import Conn, fetch_all, fetch_one
from fbi.core.clock import now


def j(x: Any) -> Any:
    """JSON-safe: numbers as numbers, instants as ISO text."""
    if isinstance(x, Decimal):
        return float(x)
    if isinstance(x, (datetime, date)):
        return x.isoformat()
    if isinstance(x, dict):
        return {str(k): j(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set)):
        return [j(v) for v in x]
    return x


LATEST_DAY_SQL = """
WITH last AS (
    SELECT DISTINCT ON (d.fixture_id, d.market_key, d.selection, d.line) d.*
      FROM intel.decisions d
     WHERE d.kickoff_at >= %(start)s AND d.kickoff_at < %(end)s
     ORDER BY d.fixture_id, d.market_key, d.selection, d.line, d.known_at DESC, d.id DESC
)
SELECT l.id, l.known_at, l.checkpoint, l.fixture_id, l.kickoff_at, th.name || ' - ' || ta.name AS match,
       c.name AS competition, c.country, l.market_key, l.selection, l.line, l.model_name, l.odds, l.n_bookmakers,
       l.p_model, l.p_cal, l.p_market, l.ev_raw, l.ev_cal, l.edge_cal, l.state, l.reasons, l.premium,
       l.parlay_eligible, l.score, l.stake_units, l.context_status, (l.context->'review'->>'decision') AS review,
       o.result_status, o.profit_flat, o.clv
  FROM last l
  JOIN core.fixtures f ON f.id = l.fixture_id
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  LEFT JOIN intel.decision_outcomes o ON o.decision_id = l.id
 WHERE (%(state)s::text IS NULL OR l.state = %(state)s) AND (%(market)s::text IS NULL OR l.market_key = %(market)s)
   AND (%(fixture)s::bigint IS NULL OR l.fixture_id = %(fixture)s)
 ORDER BY (l.state = 'RECHAZADO'), l.score DESC NULLS LAST, l.kickoff_at
 LIMIT %(limit)s
"""


def _day(day: date | None) -> date:
    return day or local_day(now())


def day_view(conn: Conn, *, day: date | None = None) -> Envelope[dict[str, Any]]:
    """EL DÍA DE PREDIGOL INTELLIGENCE: what was analysed, what became of each candidate, how deep the AI went, what it
    cost, where the news came from, the picks of the day (v6 beside v5) and the calibration behind it all."""
    d = _day(day)
    start, end = day_bounds(d)
    states = fetch_all(conn, """
        WITH last AS (SELECT DISTINCT ON (fixture_id, market_key, selection, line) state, context_status, fixture_id
                        FROM intel.decisions WHERE kickoff_at >= %(s)s AND kickoff_at < %(e)s
                       ORDER BY fixture_id, market_key, selection, line, known_at DESC, id DESC)
        SELECT state, context_status, count(*) AS n, count(DISTINCT fixture_id) AS fixtures FROM last GROUP BY 1, 2""",
                       {"s": start, "e": end})
    by_state: dict[str, int] = {}
    by_context: dict[str, int] = {}
    for r in states:
        by_state[r["state"]] = by_state.get(r["state"], 0) + int(r["n"])
        by_context[r["context_status"]] = by_context.get(r["context_status"], 0) + int(r["n"])
    fixtures = fetch_one(conn, """
        SELECT count(*) AS fixtures, count(*) FILTER (WHERE EXISTS (SELECT 1 FROM intel.decisions x
                                                                   WHERE x.fixture_id = f.id)) AS with_candidates
          FROM core.fixtures f WHERE f.kickoff_at >= %(s)s AND f.kickoff_at < %(e)s""", {"s": start, "e": end}) or {}
    passes = fetch_all(conn, """
        SELECT pass, count(*) AS n, sum(COALESCE((counts->>'web_searches')::int, 0)) AS web,
               sum(COALESCE((counts->>'l2')::int, 0)) AS l2, sum(COALESCE((counts->>'l3')::int, 0)) AS l3,
               sum(COALESCE((counts->>'marginal_saved')::int, 0)) AS marginal_saved, sum(cost_usd) AS cost_usd
          FROM ai.fixture_passes WHERE day = %(d)s GROUP BY 1 ORDER BY 1""", {"d": d})
    briefs = fetch_one(conn, """
        SELECT count(*) AS briefs, count(*) FILTER (WHERE engine = 'llm') AS llm,
               count(*) FILTER (WHERE content ? 'narrative') AS with_narrative
          FROM ai.match_briefs b JOIN core.fixtures f ON f.id = b.fixture_id
         WHERE f.kickoff_at >= %(s)s AND f.kickoff_at < %(e)s""", {"s": start, "e": end}) or {}
    usage = fetch_all(conn, """
        SELECT purpose, tier, count(*) AS calls, sum(cost_usd) AS usd, sum(input_tokens) AS tokens_in,
               sum(output_tokens) AS tokens_out FROM ai.usage WHERE at >= %(s)s AND at < %(e)s
         GROUP BY 1, 2 ORDER BY 4 DESC NULLS LAST""", {"s": start, "e": end})
    sources = fetch_all(conn, """
        SELECT e.origin, e.status, e.source_tier, count(*) AS n FROM ai.evidence e
          JOIN core.fixtures f ON f.id = e.fixture_id WHERE f.kickoff_at >= %(s)s AND f.kickoff_at < %(e)s
         GROUP BY 1, 2, 3 ORDER BY 4 DESC""", {"s": start, "e": end})
    v6 = fetch_all(conn, """
        SELECT s.kind, s.rank, s.odds, s.p_est, s.ev, s.stake_units, s.selected_at, s.decision_ids, s.detail,
               s.correlation FROM intel.day_selections s WHERE s.day = %(d)s ORDER BY s.kind, s.rank""", {"d": d})
    v5 = fetch_all(conn, """
        SELECT i.rank, i.fixture_id, th.name || ' - ' || ta.name AS match, i.market_key, i.selection, i.line, i.odds,
               i.p_model, i.p_market, i.ev, i.status, i.profit_units
          FROM picks.daily_set_items i JOIN picks.daily_sets s ON s.id = i.set_id
          JOIN core.fixtures f ON f.id = i.fixture_id JOIN core.teams th ON th.id = f.home_team_id
          JOIN core.teams ta ON ta.id = f.away_team_id
         WHERE s.day = %(d)s AND s.source = 'evaluation' ORDER BY i.rank""", {"d": d})
    report = fetch_one(conn, "SELECT revision, built_at, text, content FROM intel.daily_reports WHERE day = %(d)s "
                             "ORDER BY revision DESC LIMIT 1", {"d": d})
    runs = fetch_all(conn, "SELECT DISTINCT ON (job) job, id, started_at, finished_at, status, duration_ms, counts, "
                           "errors FROM intel.runs ORDER BY job, started_at DESC")
    return ok(j({
        "day": d, "fixtures": fixtures, "decisions": {"by_state": by_state, "by_context": by_context,
                                                      "total": sum(by_state.values())},
        "depth": {"passes": passes, "briefs": briefs}, "usage": usage,
        "cost_usd": round(sum(float(u["usd"] or 0) for u in usage), 4),
        "tokens": {"in": sum(int(u["tokens_in"] or 0) for u in usage), "out": sum(int(u["tokens_out"] or 0)
                                                                              for u in usage)},
        "sources": sources, "selections_v6": v6, "daily_set_v5": v5, "report": report, "runs": runs,
        "calibration": calibration_brief(conn),
    }))


def calibration_brief(conn: Conn) -> list[dict[str, Any]]:
    rows = fetch_all(conn, """
        WITH champ AS (
            SELECT DISTINCT ON (p.market_key, p.model_name) p.market_key, p.model_name, p.entity_id, p.to_role, p.at
              FROM intel.promotions p WHERE p.entity = 'calibrator'
             ORDER BY p.market_key, p.model_name, p.at DESC, p.id DESC
        ), edge AS (
            SELECT DISTINCT ON (market_key, model_name) market_key, model_name, to_role, at
              FROM intel.promotions WHERE entity = 'market_edge' ORDER BY market_key, model_name, at DESC, id DESC
        )
        SELECT c.market_key, c.model_name, c.to_role AS role, c.at AS since, k.method, k.params, k.known_at, k.n_train,
               k.wf->>'logloss_cal' AS logloss_cal, k.wf->>'logloss_raw' AS logloss_raw,
               k.wf->>'logloss_market' AS logloss_market, k.wf->>'ece_cal' AS ece, k.wf->>'n' AS n_oos,
               k.wf->>'days' AS days_oos, k.wf->>'rule_clv' AS rule_clv, k.wf->>'rule_n' AS rule_n,
               e.to_role AS edge, k.gate
          FROM champ c JOIN intel.calibrators k ON k.id = c.entity_id
          LEFT JOIN edge e ON e.market_key = c.market_key AND e.model_name = c.model_name
         ORDER BY c.market_key, c.model_name""")
    return [j(r) for r in rows]


def decisions(conn: Conn, *, day: date | None, state: str | None, market: str | None, fixture_id: int | None,
              limit: int) -> Envelope[dict[str, Any]]:
    d = _day(day)
    start, end = day_bounds(d)
    rows = fetch_all(conn, LATEST_DAY_SQL, {"start": start, "end": end, "state": state, "market": market,
                                            "fixture": fixture_id, "limit": limit})
    return ok(j({"day": d, "items": rows}))


def decision_detail(conn: Conn, decision_id: int) -> Envelope[dict[str, Any]]:
    d = fetch_one(conn, """
        SELECT d.*, th.name || ' - ' || ta.name AS match, c.name AS competition, b.name AS bookmaker
          FROM intel.decisions d JOIN core.fixtures f ON f.id = d.fixture_id
          JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id
          JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
          JOIN core.competitions c ON c.id = cs.competition_id
          LEFT JOIN market.bookmakers b ON b.id = d.bookmaker_id WHERE d.id = %(id)s""", {"id": decision_id})
    if d is None:
        raise ApiError(404, "not_found", "no such decision")
    pick = fetch_one(conn, """
        SELECT p.id, p.model_version_id, v.version AS model_version, r.name AS model, p.feature_set_hash,
               p.data_cutoff_ts, p.decision_rule_version, p.code_version, p.market_odds, p.odds_captured_at,
               p.p_calibrated, p.p_calibrated_lo, p.p_calibrated_hi, p.created_at
          FROM picks.picks p JOIN models.model_versions v ON v.id = p.model_version_id
          JOIN models.model_registry r ON r.id = v.model_id WHERE p.id = %(id)s""", {"id": d["pick_id"]})
    calibrator = None if d["calibrator_id"] is None else fetch_one(
        conn, "SELECT id, market_key, model_name, method, version, params, known_at, fitted_at, train_from, train_to, "
              "n_train, wf, gate FROM intel.calibrators WHERE id = %(id)s", {"id": d["calibrator_id"]})
    review = None if d["review_id"] is None else fetch_one(
        conn, "SELECT id, reviewed_at, engine_version, decision, confidence, output, cost_usd, model, status "
              "FROM ai.pick_reviews WHERE id = %(id)s", {"id": d["review_id"]})
    evidence = fetch_all(conn, """
        SELECT id, kind, claim, origin, status, source_tier, source_name, source_url, published_at, retrieved_at
          FROM ai.evidence WHERE id = ANY(%(ids)s) ORDER BY retrieved_at DESC LIMIT 40""",
                         {"ids": d["evidence_ids"] or [0]})
    outcome = fetch_one(conn, "SELECT * FROM intel.decision_outcomes WHERE decision_id = %(id)s", {"id": decision_id})
    pm = fetch_one(conn, "SELECT * FROM intel.postmortems WHERE decision_id = %(id)s ORDER BY id DESC LIMIT 1",
                   {"id": decision_id})
    history = fetch_all(conn, """
        SELECT id, known_at, checkpoint, state, odds, p_cal, ev_cal, score, stake_units, context_status
          FROM intel.decisions WHERE fixture_id = %(f)s AND market_key = %(m)s AND selection = %(s)s AND line = %(l)s
         ORDER BY known_at, id""", {"f": d["fixture_id"], "m": d["market_key"], "s": d["selection"], "l": d["line"]})
    cost = fetch_one(conn, """
        SELECT COALESCE(sum(cost_usd), 0) AS reviews_usd, count(*) AS reviews FROM ai.pick_reviews
         WHERE fixture_id = %(f)s AND market_key = %(m)s AND selection = %(s)s AND line = %(l)s
           AND engine = 'llm' AND reviewed_at <= %(k)s""",
                     {"f": d["fixture_id"], "m": d["market_key"], "s": d["selection"], "l": d["line"],
                      "k": d["known_at"]})
    return ok(j({"decision": d, "pick": pick, "calibrator": calibrator, "review": review, "evidence": evidence,
                 "outcome": outcome, "postmortem": pm, "history": history, "cost": cost}))


def dossier(conn: Conn, fixture_id: int) -> Envelope[dict[str, Any]]:
    from fbi.intel.narrative import SECTIONS, TITLES, rules_narrative

    packet = fetch_one(conn, "SELECT id, packet_version AS version, as_of, content, missing FROM ai.match_packets "
                             "WHERE fixture_id = %(f)s "
                             "ORDER BY as_of DESC, id DESC LIMIT 1", {"f": fixture_id})
    brief = fetch_one(conn, "SELECT id, created_at, pass, version, engine, model, content, cost_usd FROM ai.match_briefs "
                            "WHERE fixture_id = %(f)s ORDER BY created_at DESC, id DESC LIMIT 1", {"f": fixture_id})
    fx = fetch_one(conn, """
        SELECT f.id, f.kickoff_at, f.status_short, th.name AS home, ta.name AS away, c.name AS competition,
               c.country FROM core.fixtures f JOIN core.teams th ON th.id = f.home_team_id
          JOIN core.teams ta ON ta.id = f.away_team_id JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
          JOIN core.competitions c ON c.id = cs.competition_id WHERE f.id = %(f)s""", {"f": fixture_id})
    if fx is None:
        raise ApiError(404, "not_found", "no such fixture")
    content = (packet or {}).get("content") or {}
    narrative = ((brief or {}).get("content") or {}).get("narrative")
    engine = ((brief or {}).get("content") or {}).get("narrative_engine") or ("llm" if narrative else None)
    if not narrative and content:
        narrative, engine = rules_narrative(content, []), "rules"
    decisions_ = fetch_all(conn, """
        SELECT DISTINCT ON (market_key, selection, line) id, known_at, checkpoint, market_key, selection, line, odds,
               p_model, p_cal, p_market, ev_cal, state, score, stake_units, context_status
          FROM intel.decisions WHERE fixture_id = %(f)s ORDER BY market_key, selection, line, known_at DESC, id DESC""",
                           {"f": fixture_id})
    return ok(j({"fixture": fx, "packet": None if packet is None else {
        "id": packet["id"], "version": packet["version"], "as_of": packet["as_of"], "missing": packet["missing"]},
                 "dossier": content.get("dossier"), "stakes": content.get("stakes"), "form": content.get("form"),
                 "absences": content.get("absences"), "lineups": content.get("lineups"),
                 "narrative": None if not narrative else [{"key": k, "title": TITLES[k], "text": narrative.get(k)}
                                                          for k in SECTIONS],
                 "narrative_engine": engine,
                 "brief": None if brief is None else {"id": brief["id"], "created_at": brief["created_at"],
                                                      "pass": brief["pass"], "engine": brief["engine"],
                                                      "model": brief["model"], "summary": (brief["content"] or {}).get(
                                                          "summary"), "cost_usd": brief["cost_usd"]},
                 "decisions": decisions_}))


def calibration(conn: Conn) -> Envelope[dict[str, Any]]:
    fits = fetch_all(conn, """
        SELECT DISTINCT ON (market_key, model_name, method) id, market_key, model_name, method, version, params, known_at,
               n_train, train_from, train_to, wf - 'per_day' - 'reliability' AS wf, wf->'reliability' AS reliability, gate
          FROM intel.calibrators ORDER BY market_key, model_name, method, known_at DESC""")
    promotions = fetch_all(conn, "SELECT id, at, entity, market_key, model_name, entity_id, from_role, to_role, "
                                 "gate_version, reason FROM intel.promotions ORDER BY at DESC, id DESC LIMIT 200")
    evaluations = fetch_all(conn, """
        SELECT e.day, c.market_key, c.model_name, c.method, e.n, e.logloss_cal, e.logloss_raw, e.logloss_market,
               e.ece_cal, e.rule_n, e.rule_clv, e.rule_roi
          FROM intel.calibrator_evaluations e JOIN intel.calibrators c ON c.id = e.calibrator_id
         WHERE e.day >= %(since)s ORDER BY e.day DESC, c.market_key, c.model_name, c.method""",
                           {"since": local_day(now()) - timedelta(days=21)})
    from fbi.intel import calibration as cal

    gates = {"calib_gate": {"version": cal.GATE_VERSION, "min_oos_n": cal.MIN_OOS_N, "min_oos_days": cal.MIN_OOS_DAYS,
                            "min_gain_vs_raw": cal.MIN_GAIN_VS_RAW, "max_ece": cal.MAX_ECE,
                            "max_loss_vs_market": cal.MAX_LOSS_VS_MARKET},
             "edge_gate": {"version": cal.EDGE_GATE_VERSION, "ev_rule": cal.EV_RULE, "min_rule_n": cal.MIN_RULE_N,
                           "min_rule_clv": cal.MIN_RULE_CLV},
             "replace_gain": cal.REPLACE_GAIN, "refit_every_days": cal.REFIT_EVERY.days}
    return ok(j({"champions": calibration_brief(conn), "fits": fits, "promotions": promotions,
                 "evaluations": evaluations, "gates": gates}))


def memory(conn: Conn, *, entity_type: str | None, q: str | None, limit: int) -> Envelope[dict[str, Any]]:
    rows = fetch_all(conn, """
        SELECT DISTINCT ON (entity_type, entity_id, aspect) entity_type, entity_id, entity_name, aspect, as_of_day,
               stats, delta
          FROM intel.entity_memory
         WHERE (%(t)s::text IS NULL OR entity_type = %(t)s)
           AND (%(q)s::text IS NULL OR entity_name ILIKE '%%' || %(q)s || '%%')
         ORDER BY entity_type, entity_id, aspect, as_of_day DESC""", {"t": entity_type, "q": q})
    rows.sort(key=lambda r: -int((r["stats"] or {}).get("decisions") or (r["stats"] or {}).get("matches") or 0))
    return ok(j({"items": rows[:limit], "total": len(rows)}))


def memory_history(conn: Conn, entity_type: str, entity_id: str) -> Envelope[dict[str, Any]]:
    rows = fetch_all(conn, "SELECT aspect, as_of_day, entity_name, stats, delta, sources, built_at FROM intel.entity_memory "
                           "WHERE entity_type = %(t)s AND entity_id = %(i)s ORDER BY aspect, as_of_day",
                     {"t": entity_type, "i": entity_id})
    return ok(j({"entity_type": entity_type, "entity_id": entity_id, "history": rows}))


def reports(conn: Conn, *, day: date | None) -> Envelope[dict[str, Any]]:
    days = fetch_all(conn, "SELECT day, max(revision) AS revisions, max(built_at) AS built_at FROM intel.daily_reports "
                           "GROUP BY 1 ORDER BY 1 DESC LIMIT 60")
    target = day or (days[0]["day"] if days else None)
    rep = None if target is None else fetch_one(
        conn, "SELECT day, revision, built_at, version, content, text FROM intel.daily_reports WHERE day = %(d)s "
              "ORDER BY revision DESC LIMIT 1", {"d": target})
    return ok(j({"days": days, "report": rep}))


def markets(conn: Conn) -> Envelope[dict[str, Any]]:
    run = fetch_one(conn, "SELECT id, started_at, finished_at, status, counts FROM intel.runs WHERE job = 'weekly' "
                          "AND status IN ('ok', 'partial') ORDER BY started_at DESC LIMIT 1")
    rows = [] if run is None else fetch_all(
        conn, "SELECT provider_bet_id, name, market_key, status, criteria, metrics, proposal FROM intel.market_registry "
              "WHERE run_id = %(r)s ORDER BY CASE status WHEN 'ACTIVE' THEN 0 WHEN 'RESEARCH' THEN 1 "
              "WHEN 'CANDIDATE' THEN 2 ELSE 3 END, (metrics->>'fixtures')::int DESC NULLS LAST", {"r": run["id"]})
    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    return ok(j({"run": run, "by_status": by_status, "items": rows}))


def runs(conn: Conn, *, limit: int) -> Envelope[dict[str, Any]]:
    items = fetch_all(conn, "SELECT id, job, started_at, finished_at, status, duration_ms, counts, errors, code_version "
                            "FROM intel.runs ORDER BY started_at DESC LIMIT %(n)s", {"n": limit})
    audit = fetch_all(conn, "SELECT DISTINCT ON (rule) day, rule, n_checked, n_violations, examples, checked_at, version "
                            "FROM intel.audit_checks ORDER BY rule, checked_at DESC")
    return ok(j({"items": items, "leakage_audit": audit}))


def costs(conn: Conn) -> Envelope[dict[str, Any]]:
    """What PrediGol Intelligence costs: per match, candidate, pick, research, post-mortem, day, and the month's
    projection against the budget (US$180), with its alerts."""
    from fbi.ai import costs as ai_costs

    at = now()
    settings = AiSettings.from_env()
    today = local_day(at)
    since = day_start(today - timedelta(days=7))
    per = fetch_one(conn, """
        WITH u AS (SELECT * FROM ai.usage WHERE at >= %(s)s AND at < %(e)s)
        SELECT COALESCE(sum(cost_usd), 0) AS total,
               count(DISTINCT fixture_id) FILTER (WHERE cost_usd > 0) AS fixtures_paid,
               COALESCE(sum(cost_usd) FILTER (WHERE purpose IN ('web_search', 'evidence_extraction')), 0) AS research,
               count(DISTINCT fixture_id) FILTER (WHERE purpose = 'web_search') AS researched_fixtures,
               COALESCE(sum(cost_usd) FILTER (WHERE purpose = 'postmortem'), 0) AS postmortems,
               count(*) FILTER (WHERE purpose = 'postmortem' AND status = 'ok') AS postmortem_calls,
               COALESCE(sum(cost_usd) FILTER (WHERE purpose = 'pick_review'), 0) AS reviews,
               COALESCE(sum(cost_usd) FILTER (WHERE purpose = 'match_brief'), 0) AS briefs
          FROM u""", {"s": since, "e": day_start(today)}) or {}
    cands = fetch_one(conn, """
        SELECT count(DISTINCT (fixture_id, market_key, selection, line)) AS candidates,
               count(DISTINCT (fixture_id, market_key, selection, line)) FILTER (WHERE state <> 'RECHAZADO') AS live,
               count(DISTINCT fixture_id) AS fixtures
          FROM intel.decisions WHERE known_at >= %(s)s AND known_at < %(e)s""",
                      {"s": since, "e": day_start(today)}) or {}
    picks = fetch_one(conn, "SELECT count(*) AS picks FROM intel.day_selections WHERE kind = 'pick' AND day >= %(d)s "
                            "AND day < %(t)s", {"d": today - timedelta(days=7), "t": today}) or {}
    total = float(per.get("total") or 0)

    def per_(x: Any, n: Any) -> float | None:
        return None if not n else round(float(x or 0) / int(n), 5)

    summary = ai_costs.summary(conn, at=at, settings=settings)
    return ok(j({
        "window": {"from": today - timedelta(days=7), "to": today},
        "total_7d_usd": round(total, 4), "per_day_usd": round(total / 7, 4),
        "per_match_usd": per_(total, per.get("fixtures_paid")),
        "per_candidate_usd": per_(per.get("reviews"), cands.get("live") or cands.get("candidates")),
        "per_pick_usd": per_(total, picks.get("picks")),
        "per_research_usd": per_(per.get("research"), per.get("researched_fixtures")),
        "per_postmortem_usd": per_(per.get("postmortems"), per.get("postmortem_calls")),
        "breakdown": per, "candidates": cands, "picks": picks,
        "budget": summary.get("budget"), "projection": summary.get("projection"), "alerts": summary.get("alerts"),
        "thresholds": summary.get("thresholds"), "monthly_budget_usd": float(settings.monthly_budget),
        "month": month_start(today),
    }))
