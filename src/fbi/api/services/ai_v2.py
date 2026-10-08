"""PrediGol AI V2 for the Admin Console: the day (HOY), the research (INVESTIGACIONES), the post-mortems, what was
learned (APRENDIZAJE), the sources (FUENTES), the efficiency of the day and the shadow comparison (model alone, model
+ rules, model + AI, market). Reading only: everything here was stored by the worker (``fbi.ai``); no route calls a
model, a search API or anything that costs.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from fbi.ai import shadow as ai_shadow
from fbi.ai.calendar import day_bounds, local_day
from fbi.ai.config import TIERS, AiSettings
from fbi.ai.day import STALE_ODDS, universe
from fbi.api.contracts.ai_layer import (
    AiComparison,
    AiLearning,
    AiToday,
    ComparisonRow,
    DayFixtureRow,
    LearningNote,
    PickPostmortemRow,
    Proposal,
    ResearchRow,
    SourceRow,
)
from fbi.api.envelope import Envelope, listing, ok
from fbi.api.repositories import Conn, fetch_all, fetch_one
from fbi.core.clock import now

LEVEL_ROLE = {"bulk": ("L1", "Resumen de cada partido del día con mercado; extracción de noticias"),
              "analysis": ("L2", "Revisión de candidatos y partidos escalados"),
              "final": ("L3", "Solo los mejores picks potenciales, picks del día, parlays y contradicciones")}


def stack(settings: AiSettings) -> list[dict[str, Any]]:
    """The real stack, from the configuration (never a key)."""
    out = []
    for t in TIERS:
        tm = settings.tiers.get(t)
        level, role = LEVEL_ROLE[t]
        out.append({"level": level, "tier": t, "role": role, "provider": None if tm is None else tm.provider,
                    "model": None if tm is None else tm.model,
                    "configured": settings.tier(t) is not None})
    out.append({"level": "web", "tier": "search", "role": "Noticias, lesiones y alineaciones (caché por partido)",
                "provider": settings.search, "model": settings.search, "configured": settings.search_configured})
    return out


EFFICIENCY_SQL = """
WITH b AS (
    SELECT DISTINCT fixture_id FROM ai.match_briefs WHERE created_at >= %(start)s AND created_at < %(end)s
), latest AS (
    SELECT DISTINCT ON (r.fixture_id, r.market_key, r.selection, r.line) r.fixture_id, r.decision, r.output
      FROM ai.pick_reviews r
     WHERE r.engine = 'combined' AND r.reviewed_at >= %(start)s AND r.reviewed_at < %(end)s
       AND r.fixture_id = ANY(%(universe)s)
     ORDER BY r.fixture_id, r.market_key, r.selection, r.line, r.reviewed_at DESC, r.id DESC
)
SELECT (SELECT count(*) FROM b) AS analyzed,
       (SELECT count(*) FROM ai.match_briefs WHERE created_at >= %(start)s AND created_at < %(end)s
          AND engine = 'llm' AND status = 'ok') AS briefs_llm,
       (SELECT count(*) FROM ai.match_briefs WHERE created_at >= %(start)s AND created_at < %(end)s
          AND engine = 'rules') AS briefs_rules,
       (SELECT count(DISTINCT fixture_id) FROM ai.match_briefs WHERE created_at >= %(start)s AND created_at < %(end)s
          AND escalate) AS escalated,
       (SELECT count(*) FROM ai.pick_reviews WHERE engine = 'llm' AND status = 'ok' AND NOT output ? 'reused_from'
          AND reviewed_at >= %(start)s AND reviewed_at < %(end)s AND output->>'tier' = 'final') AS deep,
       (SELECT count(*) FROM ai.pick_reviews WHERE engine = 'llm' AND status = 'ok' AND NOT output ? 'reused_from'
          AND reviewed_at >= %(start)s AND reviewed_at < %(end)s AND COALESCE(output->>'tier', '') <> 'final')
           AS intermediate,
       (SELECT count(*) FROM latest) AS candidates,
       (SELECT count(*) FROM latest WHERE decision = 'APPROVE') AS approved,
       (SELECT count(*) FROM latest WHERE decision = 'DOWNGRADE') AS caution,
       (SELECT count(*) FROM latest WHERE decision = 'REJECT') AS rejected,
       (SELECT count(*) FROM latest WHERE decision = 'ABSTAIN') AS abstained,
       (SELECT count(*) FROM ai.usage WHERE purpose = 'web_search' AND status = 'ok' AND at >= %(start)s
          AND at < %(end)s) AS searches,
       (SELECT count(*) FROM ai.evidence WHERE retrieved_at >= %(start)s AND retrieved_at < %(end)s
          AND origin = 'web') AS news,
       (SELECT COALESCE(sum(cost_usd), 0) FROM ai.usage WHERE at >= %(start)s AND at < %(end)s) AS cost
"""


def efficiency(conn: Conn, *, at: datetime) -> dict[str, Any]:
    """PARTIDOS CON MERCADO HOY, ANALIZADOS, ANÁLISIS PROFUNDOS, CANDIDATOS, PICKS APROBADOS and what each cost."""
    day = local_day(at)
    start, end = day_bounds(day)
    today = universe(conn, day=day, at=at, scheduled_only=False)
    with_market = [f for f in today if f.has_market]
    r = fetch_one(conn, EFFICIENCY_SQL, {"start": start, "end": end,
                                         "universe": [f.fixture_id for f in with_market]}) or {}
    cost = float(r.get("cost") or 0)

    def per(n: Any) -> float | None:
        return round(cost / int(n), 4) if n else None

    return {"day": day.isoformat(), "matches_today": len(today), "with_market": len(with_market),
            "analyzed": int(r.get("analyzed") or 0), "briefs_llm": int(r.get("briefs_llm") or 0),
            "briefs_rules": int(r.get("briefs_rules") or 0), "escalated": int(r.get("escalated") or 0),
            "intermediate": int(r.get("intermediate") or 0), "deep": int(r.get("deep") or 0),
            "candidates": int(r.get("candidates") or 0), "approved": int(r.get("approved") or 0),
            "caution": int(r.get("caution") or 0), "rejected": int(r.get("rejected") or 0),
            "abstained": int(r.get("abstained") or 0), "searches": int(r.get("searches") or 0),
            "news": int(r.get("news") or 0), "cost_usd": round(cost, 4),
            "cost_per_match": per(r.get("analyzed")), "cost_per_candidate": per(r.get("candidates")),
            "cost_per_approved": per(r.get("approved"))}


def day_plan(conn: Conn, *, day: date) -> dict[str, Any] | None:
    rows = fetch_all(conn, "SELECT stage, created_at, fixtures_total, fixtures_with_market, budget, notes "
                           "FROM ai.day_plans WHERE day = %(day)s ORDER BY created_at", {"day": day})
    if not rows:
        return None
    out: dict[str, Any] = {"day": day.isoformat(), "stages": {}}
    for r in rows:
        out["stages"][r["stage"]] = {"created_at": r["created_at"].isoformat(), "fixtures_total": r["fixtures_total"],
                                     "fixtures_with_market": r["fixtures_with_market"], "budget": r["budget"],
                                     "notes": r["notes"]}
    return out


PASSES_SQL = """
SELECT fixture_id, pass, finished_at, status, escalated, reasons, counts, cost_usd
  FROM ai.fixture_passes WHERE day = %(day)s ORDER BY finished_at
"""

BRIEFS_SQL = """
SELECT DISTINCT ON (fixture_id) fixture_id, id, created_at, pass, engine, model, status, escalate, reasons, uncertainty,
       data_quality, content
  FROM ai.match_briefs WHERE fixture_id = ANY(%(fixtures)s) ORDER BY fixture_id, created_at DESC, id DESC
"""

SELECTIONS_SQL = """
SELECT DISTINCT ON (r.fixture_id, r.market_key, r.selection, r.line)
       r.id, r.fixture_id, r.market_key, r.selection, r.line, r.odds, r.p_model, r.p_market, r.edge, r.decision,
       r.engine_version, r.model, r.reviewed_at, r.output->>'reason' AS reason
  FROM ai.pick_reviews r
 WHERE r.engine = 'combined' AND r.fixture_id = ANY(%(fixtures)s) AND r.reviewed_at >= %(since)s
 ORDER BY r.fixture_id, r.market_key, r.selection, r.line, r.reviewed_at DESC, r.id DESC
"""

FIXTURE_COST_SQL = """
SELECT fixture_id, COALESCE(sum(cost_usd), 0) AS cost FROM ai.usage
 WHERE at >= %(start)s AND at < %(end)s AND fixture_id = ANY(%(fixtures)s) GROUP BY fixture_id
"""


def today_view(conn: Conn, *, day: date | None = None, at: datetime | None = None) -> Envelope[AiToday]:
    """HOY: the day's matches with a market, each with its passes, its brief, its candidates and their decisions,
    and what it cost."""
    at = at or now()
    d = day or local_day(at)
    start, end = day_bounds(d)
    fixtures = universe(conn, day=d, at=min(at, end), scheduled_only=False)
    with_market = [f for f in fixtures if f.has_market]
    ids = [f.fixture_id for f in with_market]
    passes: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for r in fetch_all(conn, PASSES_SQL, {"day": d}):
        passes[int(r["fixture_id"])].append({
            "pass": r["pass"], "at": r["finished_at"].isoformat(), "status": r["status"],
            "escalated": r["escalated"], "reasons": list(r["reasons"] or []), "counts": r["counts"] or {},
            "cost_usd": float(r["cost_usd"] or 0)})
    briefs = {int(r["fixture_id"]): r for r in fetch_all(conn, BRIEFS_SQL, {"fixtures": ids})} if ids else {}
    selections: dict[int, list[dict[str, Any]]] = defaultdict(list)
    if ids:
        for r in fetch_all(conn, SELECTIONS_SQL, {"fixtures": ids, "since": start - timedelta(hours=12)}):
            selections[int(r["fixture_id"])].append({
                "review_id": r["id"], "market": r["market_key"], "selection": r["selection"], "line": str(r["line"]),
                "odds": None if r["odds"] is None else float(r["odds"]),
                "p_model": None if r["p_model"] is None else float(r["p_model"]),
                "p_market": None if r["p_market"] is None else float(r["p_market"]),
                "edge": None if r["edge"] is None else float(r["edge"]), "decision": r["decision"],
                "by_llm": not str(r["engine_version"]).endswith("+none"), "model": r["model"],
                "reason": r["reason"], "reviewed_at": r["reviewed_at"].isoformat()})
    costs = {int(r["fixture_id"]): float(r["cost"]) for r in
             fetch_all(conn, FIXTURE_COST_SQL, {"start": start, "end": end, "fixtures": ids})} if ids else {}
    rows = []
    for f in with_market:
        b = briefs.get(f.fixture_id)
        rows.append(DayFixtureRow(
            fixture_id=f.fixture_id, match=f"{f.home} - {f.away}", competition=f.competition, kickoff_at=f.kickoff_at,
            has_market=True, odds_age_minutes=None if f.odds_at is None else int((at - f.odds_at).total_seconds() // 60),
            priority=f.priority, important=f.important, passes=passes.get(f.fixture_id, []),
            brief=None if b is None else {
                "id": b["id"], "created_at": b["created_at"].isoformat(), "pass": b["pass"], "engine": b["engine"],
                "model": b["model"], "status": b["status"], "escalate": b["escalate"],
                "reasons": list(b["reasons"] or []), "uncertainty": b["uncertainty"],
                "data_quality": b["data_quality"], "summary": (b["content"] or {}).get("summary"),
                "injuries": (b["content"] or {}).get("injuries", []), "changes": (b["content"] or {}).get("changes", []),
                "context": (b["content"] or {}).get("context", [])},
            selections=selections.get(f.fixture_id, []), cost_usd=round(costs.get(f.fixture_id, 0.0), 6)))
    stale = sum(1 for f in with_market if f.odds_at is not None and at - f.odds_at > STALE_ODDS)
    totals = {"with_market": len(with_market), "passes": sum(len(v) for v in passes.values()),
              "escalated": sum(1 for r in rows if r.brief and r.brief.get("escalate")),
              "stale_odds": stale, "cost_usd": round(sum(costs.values()), 6)}
    return ok(AiToday(day=d, plan=day_plan(conn, day=d), fixtures=rows,
                      without_market=len(fixtures) - len(with_market), totals=totals))


SEARCHES_SQL = """
SELECT u.fixture_id, u.at, u.status, u.cost_usd, u.error, u.input_hash
  FROM ai.usage u WHERE u.purpose = 'web_search' AND u.at >= %(start)s AND u.at < %(end)s AND u.fixture_id IS NOT NULL
 ORDER BY u.at
"""

RESEARCH_EVIDENCE_SQL = """
SELECT e.id, e.fixture_id, e.kind, e.claim, e.origin, e.source_name, e.source_url, e.source_domain, e.source_tier,
       e.published_at, e.retrieved_at, e.last_seen_at, e.seen_count, e.status, e.status_reason, e.attributes,
       e.confidence, e.relevance, t.name AS team
  FROM ai.evidence e LEFT JOIN core.teams t ON t.id = e.team_id
 WHERE e.fixture_id = ANY(%(fixtures)s) AND (e.origin = 'web' OR e.retrieved_at >= %(start)s - interval '2 days')
 ORDER BY e.fixture_id, e.retrieved_at DESC, e.id DESC
"""

MATCHES_SQL = """
SELECT f.id, th.name || ' - ' || ta.name AS match, f.kickoff_at FROM core.fixtures f
  JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id WHERE f.id = ANY(%(ids)s)
"""


def research(conn: Conn, *, day: date | None = None) -> Envelope[list[ResearchRow]]:
    """INVESTIGACIONES: per match of the day, every search made (when, what it cost, how it ended) and every piece
    of evidence with its source, link, dates, level and status - first seen, last seen and how often."""
    d = day or local_day(now())
    start, end = day_bounds(d)
    searches: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for r in fetch_all(conn, SEARCHES_SQL, {"start": start, "end": end}):
        searches[int(r["fixture_id"])].append({"at": r["at"].isoformat(), "status": r["status"],
                                               "cost_usd": float(r["cost_usd"]), "error": r["error"]})
    with_briefs = [int(r["fixture_id"]) for r in fetch_all(
        conn, "SELECT DISTINCT fixture_id FROM ai.match_briefs WHERE created_at >= %(start)s AND created_at < %(end)s",
        {"start": start, "end": end})]
    ids = sorted(set(searches) | set(with_briefs))
    if not ids:
        return listing([], empty_reason="no_research_today")
    evidence: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for r in fetch_all(conn, RESEARCH_EVIDENCE_SQL, {"fixtures": ids, "start": start}):
        evidence[int(r["fixture_id"])].append({
            "id": r["id"], "kind": r["kind"], "claim": r["claim"], "origin": r["origin"], "team": r["team"],
            "source": r["source_name"], "url": r["source_url"], "domain": r["source_domain"], "tier": r["source_tier"],
            "published_at": None if r["published_at"] is None else r["published_at"].isoformat(),
            "retrieved_at": r["retrieved_at"].isoformat(),
            "last_seen_at": None if r["last_seen_at"] is None else r["last_seen_at"].isoformat(),
            "seen_count": r["seen_count"], "status": r["status"], "status_reason": r["status_reason"],
            "confidence": float(r["confidence"]), "relevance": float(r["relevance"]),
            "title": (r["attributes"] or {}).get("result_title"), "player": (r["attributes"] or {}).get("player_name")})
    matches = {int(r["id"]): r for r in fetch_all(conn, MATCHES_SQL, {"ids": ids})}
    rows = [ResearchRow(fixture_id=fid, match=matches[fid]["match"], kickoff_at=matches[fid]["kickoff_at"],
                        searches=searches.get(fid, []), evidence=evidence.get(fid, [])[:60],
                        cost_usd=round(sum(s["cost_usd"] for s in searches.get(fid, [])), 6))
            for fid in ids if fid in matches]
    rows.sort(key=lambda r: r.kickoff_at)
    return listing(rows, empty_reason="no_research_today")


POSTMORTEMS_SQL = """
SELECT pm.id, pm.fixture_id, th.name || ' - ' || ta.name AS match, c.name AS competition, f.kickoff_at, pm.market_key,
       pm.selection, pm.line, pm.roles, pm.decision, pm.settled, pm.verdict, pm.classification, pm.odds, pm.close_odds,
       pm.clv, pm.p_model, pm.p_market, pm.answers, pm.narrative, pm.created_at
  FROM ai.pick_postmortems pm JOIN core.fixtures f ON f.id = pm.fixture_id
  JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id JOIN core.competitions c ON c.id = cs.competition_id
 WHERE f.kickoff_at >= %(start)s AND f.kickoff_at < %(end)s
   AND (%(verdict)s::text IS NULL OR pm.verdict = %(verdict)s)
   AND (%(cls)s::text IS NULL OR pm.classification = %(cls)s)
 ORDER BY (pm.verdict IN ('approved_lost', 'caution_lost', 'rejected_would_have_won')) DESC, f.kickoff_at DESC, pm.id
 LIMIT %(limit)s
"""


def postmortems(conn: Conn, *, day: date | None = None, verdict: str | None = None, classification: str | None = None,
                limit: int = 200) -> Envelope[list[PickPostmortemRow]]:
    """POST-MORTEMS of the selections of a Bogotá day's matches (default yesterday): the ten questions, the class of
    a loss, the narrative."""
    d = day or (local_day(now()) - timedelta(days=1))
    start, end = day_bounds(d)
    rows = fetch_all(conn, POSTMORTEMS_SQL, {"start": start, "end": end, "verdict": verdict, "cls": classification,
                                             "limit": limit})
    return listing([PickPostmortemRow.model_validate(r | {"roles": list(r["roles"] or [])}) for r in rows],
                   empty_reason="no_postmortems")


NOTES_SQL = """
SELECT id, day, created_at, kind, title, body, n, evidence, engine FROM ai.learning_notes
 WHERE (%(day)s::date IS NOT NULL AND day = %(day)s) OR (%(created)s::date IS NOT NULL
        AND created_at >= %(start)s AND created_at < %(end)s)
 ORDER BY CASE kind WHEN 'lesson' THEN 0 WHEN 'summary' THEN 1 ELSE 2 END, id
"""

PROPOSALS_SQL = """
SELECT id, created_at, title, hypothesis, rationale, target, status, proposed_by, evidence
  FROM analytics.research_hypotheses
 WHERE status IN ('PROPOSED', 'INVESTIGATING') ORDER BY created_at DESC, id DESC LIMIT %(limit)s
"""


def _proposal(r: dict[str, Any]) -> Proposal:
    ev = dict(r.get("evidence") or {})
    n = ev.get("n_matches", ev.get("n", ev.get("losses")))
    return Proposal(id=r["id"], created_at=r["created_at"], title=r["title"], hypothesis=r["hypothesis"],
                    rationale=r.get("rationale"), target=r.get("target") or "other", status=r["status"],
                    proposed_by=r["proposed_by"], n_matches=None if n is None else int(n),
                    impact=None if ev.get("impact") is None else str(ev["impact"]),
                    investigation_cost=None if ev.get("investigation_cost") is None else str(ev["investigation_cost"]),
                    evidence=ev)


def notes_learned_on(conn: Conn, created: date) -> list[LearningNote]:
    start, end = day_bounds(created)
    return [LearningNote.model_validate(r) for r in
            fetch_all(conn, NOTES_SQL, {"day": None, "created": created, "start": start, "end": end})]


def proposals(conn: Conn, *, limit: int = 20) -> list[Proposal]:
    return [_proposal(r) for r in fetch_all(conn, PROPOSALS_SQL, {"limit": limit})]


def learning(conn: Conn, *, day: date | None = None) -> Envelope[AiLearning]:
    """APRENDIZAJE: the notes and lessons of a day's results (default yesterday's, learned this morning) and the
    improvements proposed and awaiting the owner."""
    d = day or (local_day(now()) - timedelta(days=1))
    notes = [LearningNote.model_validate(r) for r in
             fetch_all(conn, NOTES_SQL, {"day": d, "created": None, "start": None, "end": None})]
    return ok(AiLearning(day=d, notes=notes, proposals=proposals(conn)))


SOURCES_SQL = """
SELECT s.domain, max(s.tier) AS tier, sum(s.results) AS results, sum(s.evidence) AS evidence, sum(s.useful) AS useful,
       sum(s.discarded) AS discarded, sum(s.cost_usd) AS cost_usd
  FROM ai.source_stats s WHERE s.day >= %(since)s AND s.day <= %(until)s
 GROUP BY s.domain ORDER BY sum(s.useful) DESC, sum(s.results) DESC, s.domain LIMIT %(limit)s
"""


def sources(conn: Conn, *, days: int = 7, limit: int = 100) -> Envelope[list[SourceRow]]:
    """FUENTES: per domain over the last days - Consultas (times it came up), Evidencias útiles, Evidencias
    descartadas, Costo, Tasa de utilidad."""
    until = local_day(now())
    rows = []
    for r in fetch_all(conn, SOURCES_SQL, {"since": until - timedelta(days=days - 1), "until": until, "limit": limit}):
        results, useful = int(r["results"] or 0), int(r["useful"] or 0)
        rows.append(SourceRow(domain=r["domain"], tier=r["tier"], results=results, evidence=int(r["evidence"] or 0),
                              useful=useful, discarded=int(r["discarded"] or 0),
                              cost_usd=round(float(r["cost_usd"] or 0), 6),
                              utility=round(useful / results, 4) if results else None))
    return listing(rows, empty_reason="no_sources_yet")


ARMS = (("model", "Modelo solo"), ("model_rules", "Modelo + reglas"), ("model_ai", "Modelo + IA (reglas + LLM)"),
        ("market", "Mercado"))


def _row(arm: str, label: str, m: dict[str, Any], *, market: bool = False) -> ComparisonRow:
    def g(k: str) -> float | None:
        v = m.get(k)
        return None if v is None else float(v)
    if market:
        return ComparisonRow(arm=arm, label=label, n=int(m.get("n") or 0),  # type: ignore[arg-type]
                             logloss=g("logloss_market"), brier=g("brier_market"), ece=g("ece_market"), roi=None,
                             clv=None, ev_claimed=None, ev_market=None, hit_rate=None, max_drawdown=None)
    return ComparisonRow(arm=arm, label=label, n=int(m.get("n") or 0),  # type: ignore[arg-type]
                         logloss=g("logloss_model"), brier=g("brier_model"), ece=g("ece_model"), roi=g("roi"),
                         clv=g("clv"), ev_claimed=g("ev_claimed"), ev_market=g("ev_market"), hit_rate=g("hit_rate"),
                         max_drawdown=g("max_drawdown"))


def comparison(conn: Conn) -> Envelope[AiComparison]:
    """MODELO SOLO / MODELO + REGLAS / MODELO + IA / MERCADO on the same settled selections (the AI's shadow
    report): log loss, Brier, calibration, ROI, CLV, the EV claimed and by the market's price, hit rate,
    drawdown."""
    reports = {r["engine"]: r for r in ai_shadow.latest(conn)}
    combined = reports.get("combined") or {}
    rules = reports.get("rules") or {}
    arms_c = combined.get("arms") or {}
    arms_r = rules.get("arms") or {}
    rows = [_row("model", "Modelo solo", arms_c.get("model") or {}),
            _row("model_rules", "Modelo + reglas", arms_r.get("model_ai") or {}),
            _row("model_ai", "Modelo + IA (reglas + LLM)", arms_c.get("model_ai") or {}),
            _row("market", "Mercado", arms_c.get("model") or {}, market=True)]
    gate = combined.get("gate") or {}
    checks = gate.get("checks") or {}
    return ok(AiComparison(rows=rows, window_from=combined.get("window_from"), window_to=combined.get("window_to"),
                           verdict=gate.get("verdict"),
                           sample={k: (v or {}).get("value") for k, v in checks.items()
                                   if k in ("selections", "days", "rejected")}))


def overview_extra(conn: Conn, *, at: datetime, settings: AiSettings) -> dict[str, Any]:
    from fbi.ai import costs as ai_costs

    return {"projection": ai_costs.projection(conn, at=at, settings=settings), "alerts": ai_costs.alerts(conn, at=at),
            "stack": stack(settings), "efficiency": efficiency(conn, at=at),
            "day": day_plan(conn, day=local_day(at))}


def day_counts(conn: Conn, *, day: date) -> dict[str, Any]:
    """EL DÍA EN PREDIGOL AI."""
    start, end = day_bounds(day)
    r = fetch_one(conn, DAY_SQL, {"start": start, "end": end, "day": day}) or {}
    return {k: (float(v) if isinstance(v, Decimal) else int(v or 0)) for k, v in r.items()}


DAY_SQL = """
SELECT (SELECT COALESCE(max(fixtures_with_market), 0) FROM ai.day_plans WHERE day = %(day)s) AS with_market,
       (SELECT count(DISTINCT fixture_id) FROM ai.match_briefs WHERE created_at >= %(start)s AND created_at < %(end)s)
           AS matches_analyzed,
       (SELECT count(*) FROM ai.usage WHERE purpose = 'web_search' AND status = 'ok' AND at >= %(start)s
          AND at < %(end)s) AS searches,
       (SELECT count(*) FROM ai.evidence WHERE origin = 'web' AND retrieved_at >= %(start)s AND retrieved_at < %(end)s)
           AS news,
       (SELECT count(*) FROM ai.evidence WHERE kind IN ('injury', 'suspension', 'doubtful') AND retrieved_at >= %(start)s
          AND retrieved_at < %(end)s) AS injuries,
       (SELECT count(*) FROM ai.evidence WHERE kind = 'lineup' AND retrieved_at >= %(start)s AND retrieved_at < %(end)s)
           AS lineups,
       (SELECT count(DISTINCT (fixture_id, market_key, selection, line)) FROM ai.pick_reviews WHERE engine = 'combined'
          AND reviewed_at >= %(start)s AND reviewed_at < %(end)s) AS candidates,
       (SELECT count(*) FROM ai.pick_reviews WHERE engine = 'llm' AND status = 'ok' AND NOT output ? 'reused_from'
          AND reviewed_at >= %(start)s AND reviewed_at < %(end)s) AS llm_reviews,
       (SELECT count(*) FROM ai.pick_reviews WHERE engine = 'llm' AND status = 'ok' AND NOT output ? 'reused_from'
          AND output->>'tier' = 'final' AND reviewed_at >= %(start)s AND reviewed_at < %(end)s) AS deep_reviews,
       (SELECT count(*) FROM ai.pick_postmortems WHERE created_at >= %(start)s AND created_at < %(end)s) AS postmortems,
       (SELECT count(*) FROM ai.pick_postmortems WHERE created_at >= %(start)s AND created_at < %(end)s
          AND settled IN ('loss', 'half_loss')) AS losses_investigated,
       (SELECT count(*) FROM ai.learning_notes WHERE created_at >= %(start)s AND created_at < %(end)s) AS findings,
       (SELECT count(*) FROM analytics.research_hypotheses WHERE created_at >= %(start)s AND created_at < %(end)s)
           AS hypotheses,
       (SELECT COALESCE(sum(cost_usd), 0) FROM ai.usage WHERE at >= %(start)s AND at < %(end)s) AS cost
"""


__all__ = ["comparison", "day_counts", "day_plan", "efficiency", "learning", "notes_learned_on", "overview_extra",
           "postmortems", "proposals", "research", "sources", "stack", "today_view"]
