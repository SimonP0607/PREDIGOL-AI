"""The AI decision layer, read for the product and the Admin Console. Never a model call: everything here is
read from what the worker stored (``fbi.ai``); the owner's "run now" is a queued request the worker picks up.

Who sees a match analysis: a user sees the cards whose pick is QUALIFIED and the model's view of unpriced
markets (labelled evaluation); the owner's evaluation mode sees every card. A shadow pick's numbers never
reach a user.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from psycopg.rows import tuple_row

from fbi.ai import costs as ai_costs
from fbi.ai import shadow as ai_shadow
from fbi.ai.config import AiSettings
from fbi.ai.gating import enforcement
from fbi.ai.text import shown as owner_text
from fbi.ai.usage import budget
from fbi.analyst.db import write_connection
from fbi.api.contracts.ai_layer import (
    AiOverview,
    AnalysisCard,
    BriefView,
    CardNotes,
    Claim,
    CycleRow,
    EvidenceRow,
    EvolutionDashboard,
    MatchAnalysis,
    MemoryEvent,
    PacketView,
    ReviewDetail,
    ReviewRow,
    RunIn,
    RunQueued,
    UsageRow,
)
from fbi.api.envelope import DataStatus, Envelope, listing, ok, unavailable
from fbi.api.errors import ApiError
from fbi.api.repositories import Conn, fetch_all, fetch_one
from fbi.api.services import ai_v2
from fbi.core.clock import now
from fbi.picks.daily import DAY_TZ

ANALYSIS_SQL = """
SELECT a.id, a.fixture_id, a.built_at, a.market_observed, a.cards, a.summary, a.engines
  FROM ai.match_analyses a WHERE a.fixture_id = %(fixture)s
 ORDER BY a.built_at DESC, a.id DESC LIMIT 1
"""


BRIEF_SQL = """
SELECT b.id, b.created_at, b.pass, b.engine, b.model, b.status, b.escalate, b.reasons, b.uncertainty, b.data_quality,
       b.content
  FROM ai.match_briefs b WHERE b.fixture_id = %(fixture)s ORDER BY b.created_at DESC, b.id DESC LIMIT 1
"""

IN_DAY_SQL = """
SELECT EXISTS (SELECT 1 FROM ai.fixture_passes WHERE fixture_id = %(fixture)s AND day = %(day)s) AS in_day
"""


def _claim(c: dict[str, Any]) -> Claim:
    """A brief's claim as the owner reads it (plain words, also for briefs stored before brief-v3)."""
    return Claim.model_validate(c | {"text": owner_text(str(c.get("text") or ""))})


def _notes_for(card: AnalysisCard, notes: list[dict[str, Any]]) -> CardNotes | None:
    from fbi.ai.brief import line_text

    key = (card.market, card.selection, line_text(card.line))
    for n in notes:
        if (n.get("market"), n.get("selection"), str(n.get("line"))) == key:
            return CardNotes(why=[_claim(c) for c in n.get("why", [])], risks=[_claim(c) for c in n.get("risks", [])])
    return None


def match_analysis(conn: Conn, fixture_id: int, *, evaluation: bool) -> Envelope[MatchAnalysis | None]:
    settings = AiSettings.from_env()
    row = fetch_one(conn, ANALYSIS_SQL, {"fixture": fixture_id})
    if row is None:
        return unavailable(None, "no_analysis_yet", status=DataStatus.EMPTY)
    enf = enforcement(conn, settings)
    cards = [AnalysisCard.model_validate(c) for c in (row["cards"] or [])]
    shown = cards if evaluation else [c for c in cards if c.kind == "no_market" or c.qualified]
    brief_row = fetch_one(conn, BRIEF_SQL, {"fixture": fixture_id})
    ai_visible = evaluation or enf.enforced
    if not evaluation and not enf.enforced:
        # Shadow: a user sees nothing the AI decided - the value gate's own verdict, never a review's.
        shown = [c.model_copy(update={"ai": None, "verdict": "recommended", "verdict_reason": "value"})
                 if c.kind == "value" else c.model_copy(update={"ai": None}) for c in shown]
    brief: BriefView | None = None
    if brief_row is not None and ai_visible:
        content = brief_row["content"] or {}
        notes = list(content.get("cards") or [])
        shown = [c.model_copy(update={"notes": _notes_for(c, notes)}) for c in shown]
        brief = BriefView(id=brief_row["id"], created_at=brief_row["created_at"], pass_kind=brief_row["pass"],
                          engine=brief_row["engine"], model=brief_row["model"], status=brief_row["status"],
                          escalate=bool(brief_row["escalate"]), reasons=list(brief_row["reasons"] or []),
                          uncertainty=brief_row["uncertainty"], data_quality=brief_row["data_quality"],
                          summary=owner_text(content.get("summary")),
                          context=[_claim(c) for c in content.get("context", [])],
                          injuries=list(content.get("injuries") or []),
                          changes=[_claim(c) for c in content.get("changes", [])])
    updated = row["built_at"]
    if brief is not None and brief.created_at > updated:
        updated = brief.created_at
    in_day = fetch_one(conn, IN_DAY_SQL, {"fixture": fixture_id, "day": now().astimezone(DAY_TZ).date()}) or {}
    return ok(MatchAnalysis(
        fixture_id=fixture_id, built_at=row["built_at"], audience="evaluation" if evaluation else "user",
        mode=settings.mode, enforced=enf.enforced, market_observed=bool(row["market_observed"]),
        engines=list(row["engines"] or []), analyzed_by_llm="llm" in (row["engines"] or []), cards=shown,
        withheld=len(cards) - len(shown), missing=list((row["summary"] or {}).get("missing") or []), brief=brief,
        updated_at=updated, in_ai_day=bool(in_day.get("in_day"))))


# ── Admin Console ────────────────────────────────────────────────────────────

CYCLES_SQL = """
SELECT DISTINCT ON (kind) id, kind, started_at, finished_at, status, mode, budget_state, counts, cost_usd, error
  FROM ai.cycles ORDER BY kind, started_at DESC, id DESC
"""

TODAY_SQL = """
SELECT (SELECT count(*) FROM ai.match_packets WHERE built_at >= %(since)s) AS packets,
       (SELECT count(DISTINCT fixture_id) FROM ai.match_packets WHERE built_at >= %(since)s) AS matches,
       (SELECT count(*) FROM ai.match_analyses WHERE built_at >= %(since)s) AS analyses,
       (SELECT count(*) FROM ai.evidence WHERE retrieved_at >= %(since)s) AS evidence,
       (SELECT count(*) FROM ai.pick_reviews WHERE engine = 'combined' AND reviewed_at >= %(since)s) AS reviews,
       (SELECT count(*) FROM ai.pick_reviews WHERE engine = 'llm' AND reviewed_at >= %(since)s) AS llm_reviews
"""


def overview(conn: Conn, *, at: datetime | None = None) -> Envelope[AiOverview]:
    at = at or now()
    settings = AiSettings.from_env()
    day = datetime.combine(at.astimezone(DAY_TZ).date(), time(0), tzinfo=DAY_TZ)
    enf = enforcement(conn, settings)
    today = fetch_one(conn, TODAY_SQL, {"since": day}) or {}
    extra = ai_v2.overview_extra(conn, at=at, settings=settings)
    return ok(AiOverview(
        settings=settings.public(), budget=budget(conn, at=at, settings=settings).as_json(),
        enforcement={"enforced": enf.enforced, "reason": enf.reason,
                     "gate_verdict": (enf.gate or {}).get("verdict")},
        last_cycles=[CycleRow.model_validate(r) for r in fetch_all(conn, CYCLES_SQL)],
        today={k: int(v or 0) for k, v in today.items()},
        shadow=[_shadow_row(r) for r in ai_shadow.latest(conn)], **extra))


def _shadow_row(r: dict[str, Any]) -> dict[str, Any]:
    gate = r.get("gate") or {}
    return {"engine": r["engine"], "created_at": r["created_at"].isoformat(), "window_from": str(r["window_from"]),
            "window_to": str(r["window_to"]), "verdict": gate.get("verdict"), "checks": gate.get("checks"),
            "arms": r.get("arms") or {}}


REVIEWS_SQL = """
SELECT r.id, r.reviewed_at, r.fixture_id, th.name || ' - ' || ta.name AS match, f.kickoff_at, c.name AS competition,
       r.market_key, r.selection, r.line, r.odds, r.p_model, r.p_market, r.edge, r.decision, r.confidence, r.engine,
       r.engine_version, r.model, r.output->>'reason' AS reason, r.status, r.mode, r.cost_usd
  FROM ai.pick_reviews r JOIN core.fixtures f ON f.id = r.fixture_id
  JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id JOIN core.competitions c ON c.id = cs.competition_id
 WHERE r.reviewed_at >= %(since)s AND r.reviewed_at < %(until)s AND r.engine = %(engine)s
   AND (%(decision)s::text IS NULL OR r.decision = %(decision)s) AND (%(fixture)s::bigint IS NULL OR r.fixture_id = %(fixture)s)
 ORDER BY r.reviewed_at DESC, r.id DESC LIMIT %(limit)s
"""


def reviews(conn: Conn, *, day: date | None, engine: str, decision: str | None, fixture_id: int | None,
            limit: int) -> Envelope[list[ReviewRow]]:
    d = day or now().astimezone(DAY_TZ).date()
    since = datetime.combine(d, time(0), tzinfo=DAY_TZ)
    if fixture_id is not None:
        since = since - timedelta(days=14)
    rows = fetch_all(conn, REVIEWS_SQL, {"since": since, "until": datetime.combine(d, time(0), tzinfo=DAY_TZ)
                                         + timedelta(days=1), "engine": engine, "decision": decision,
                                         "fixture": fixture_id, "limit": limit})
    return listing([ReviewRow.model_validate(r) for r in rows], empty_reason="no_reviews")


def review_detail(conn: Conn, review_id: int) -> Envelope[ReviewDetail]:
    one = REVIEWS_SQL.replace("WHERE r.reviewed_at >= %(since)s AND r.reviewed_at < %(until)s AND r.engine = %(engine)s\n"
                              "   AND (%(decision)s::text IS NULL OR r.decision = %(decision)s) AND (%(fixture)s::bigint "
                              "IS NULL OR r.fixture_id = %(fixture)s)", "WHERE r.id = %(id)s")
    row = fetch_one(conn, one.replace("LIMIT %(limit)s", ""), {"id": review_id})
    if row is None:
        raise ApiError(404, "not_found", "no such review")
    full = fetch_one(conn, "SELECT output, sources, evidence_ids, packet_id, usage_ids, input_hash FROM ai.pick_reviews "
                           "WHERE id = %(id)s", {"id": review_id}) or {}
    evidence = fetch_all(conn, "SELECT id, kind, claim, origin, source_name, source_url, source_tier, status, "
                               "status_reason, published_at, retrieved_at FROM ai.evidence WHERE id = ANY(%(ids)s)",
                         {"ids": list(full.get("evidence_ids") or [])})
    packet = None
    if full.get("packet_id"):
        packet = fetch_one(conn, "SELECT id, packet_hash, as_of, approx_tokens, missing, content FROM ai.match_packets "
                                 "WHERE id = %(id)s", {"id": full["packet_id"]})
    output = dict(full.get("output") or {})
    component_ids = [int(e["review_id"]) for e in output.get("engines", []) if e.get("review_id")]
    components = []
    for cid in component_ids:
        c = fetch_one(conn, one.replace("LIMIT %(limit)s", ""), {"id": cid})
        if c is not None:
            components.append(ReviewRow.model_validate(c))
    usage_ids = list(full.get("usage_ids") or [])
    for comp in components:
        u = fetch_one(conn, "SELECT usage_ids FROM ai.pick_reviews WHERE id = %(id)s", {"id": comp.id})
        usage_ids += list((u or {}).get("usage_ids") or [])
    usage = fetch_all(conn, "SELECT id, at, purpose, tier, provider, model, prompt_version, input_tokens, output_tokens, "
                            "cached_tokens, searches, cost_usd, latency_ms, status, error FROM ai.usage "
                            "WHERE id = ANY(%(ids)s) ORDER BY id", {"ids": sorted(set(usage_ids))})
    return ok(ReviewDetail(review=ReviewRow.model_validate(row), output=output, sources=list(full.get("sources") or []),
                           evidence=[dict(e) for e in evidence], packet=None if packet is None else dict(packet),
                           components=components, usage=[UsageRow.model_validate(u) for u in usage],
                           input_hash=str(full.get("input_hash") or "")))


def packet(conn: Conn, fixture_id: int) -> Envelope[PacketView | None]:
    row = fetch_one(conn, "SELECT id, fixture_id, packet_version, as_of, built_at, packet_hash, approx_tokens, missing, "
                          "content, sources FROM ai.match_packets WHERE fixture_id = %(f)s ORDER BY as_of DESC, id DESC "
                          "LIMIT 1", {"f": fixture_id})
    if row is None:
        return unavailable(None, "no_packet_yet", status=DataStatus.EMPTY)
    history = fetch_all(conn, "SELECT id, as_of, packet_hash, approx_tokens, missing FROM ai.match_packets "
                              "WHERE fixture_id = %(f)s ORDER BY as_of DESC, id DESC LIMIT 50", {"f": fixture_id})
    return ok(PacketView(**{k: row[k] for k in ("id", "fixture_id", "packet_version", "as_of", "built_at", "packet_hash",
                                                "approx_tokens", "missing", "content", "sources")},
                         history=[{**dict(h), "as_of": h["as_of"].isoformat()} for h in history]))


EVIDENCE_SQL = """
SELECT e.id, e.fixture_id, CASE WHEN f.id IS NULL THEN NULL ELSE th.name || ' - ' || ta.name END AS match,
       t.name AS team, e.kind, e.claim, e.origin, e.source_name, e.source_url, e.source_tier, e.published_at,
       e.retrieved_at, e.status, e.status_reason, e.status_history, e.attributes
  FROM ai.evidence e
  LEFT JOIN core.fixtures f ON f.id = e.fixture_id
  LEFT JOIN core.teams th ON th.id = f.home_team_id LEFT JOIN core.teams ta ON ta.id = f.away_team_id
  LEFT JOIN core.teams t ON t.id = e.team_id
 WHERE (%(fixture)s::bigint IS NULL OR e.fixture_id = %(fixture)s) AND (%(status)s::text IS NULL OR e.status = %(status)s)
   AND (%(fixture)s::bigint IS NOT NULL OR e.retrieved_at >= %(since)s)
 ORDER BY e.retrieved_at DESC, e.id DESC LIMIT %(limit)s
"""


def evidence(conn: Conn, *, fixture_id: int | None, status: str | None, limit: int) -> Envelope[list[EvidenceRow]]:
    rows = fetch_all(conn, EVIDENCE_SQL, {"fixture": fixture_id, "status": status, "since": now() - timedelta(days=3),
                                          "limit": limit})
    return listing([EvidenceRow.model_validate(r) for r in rows], empty_reason="no_evidence")


def cost_summary(conn: Conn) -> Envelope[dict[str, Any]]:
    at = now()
    settings = AiSettings.from_env()
    out = ai_costs.summary(conn, at=at, settings=settings)
    w = workload(conn, at=at)
    out["workload"] = w.__dict__
    out["simulation"] = [ai_costs.simulate(w, p, day=at.date()) for p in ai_costs.PROFILES]
    out["worst_case"] = [ai_costs.simulate(ai_costs.worst_case(settings, w), p, day=at.date())
                         for p in ai_costs.PROFILES]
    return ok(out)


WORKLOAD_SQL = """
SELECT (SELECT count(*) FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
          JOIN core.competitions c ON c.id = cs.competition_id
         WHERE c.is_tracked AND f.kickoff_at >= %(since)s AND f.kickoff_at < %(until)s)::float / 14 AS matches,
       (SELECT count(*) FROM ai.pick_reviews WHERE engine = 'combined' AND reviewed_at >= %(since)s
          AND reviewed_at < %(until)s)::float / 14 AS reviews,
       (SELECT count(DISTINCT (fixture_id, market_key, selection, line)) FROM ai.pick_reviews WHERE engine = 'combined'
          AND reviewed_at >= %(since)s AND reviewed_at < %(until)s)::float / 14 AS shortlist,
       (SELECT avg(approx_tokens) FROM ai.match_packets WHERE built_at >= %(since)s) AS packet_tokens
"""


def workload(conn: Conn, *, at: datetime) -> ai_costs.Workload:
    """A typical day from the last 14 days of the platform's own counts."""
    r = fetch_one(conn, WORKLOAD_SQL, {"since": at - timedelta(days=14), "until": at}) or {}
    shortlist = float(r.get("shortlist") or 0)
    packet_tokens = int(r.get("packet_tokens") or 2000)
    settings = AiSettings.from_env()
    llm = min(float(settings.max_llm_reviews_per_day), shortlist * 0.6)
    return ai_costs.Workload(matches=float(r.get("matches") or 0), shortlist=shortlist, llm_reviews=llm,
                             deep_reviews=min(float(settings.max_deep_per_day), llm * 0.2),
                             web_fixtures=min(12.0, shortlist / 2), review_in=packet_tokens + 1800, review_out=700,
                             notes={"packet_tokens": packet_tokens, "reviews_per_day": float(r.get("reviews") or 0)})


def shadow_reports(conn: Conn) -> Envelope[list[dict[str, Any]]]:
    return listing([_shadow_row(r) for r in ai_shadow.latest(conn)], empty_reason="no_shadow_report_yet")


MEMORY_SQL = """
SELECT id, created_at, kind, entity_type, entity_id, fixture_id, hypothesis, evidence, result, confidence, version
  FROM ai.memory_events WHERE (%(kind)s::text IS NULL OR kind = %(kind)s)
 ORDER BY created_at DESC, id DESC LIMIT %(limit)s
"""


def memory(conn: Conn, *, kind: str | None, limit: int) -> Envelope[list[MemoryEvent]]:
    return listing([MemoryEvent.model_validate(r) for r in fetch_all(conn, MEMORY_SQL, {"kind": kind, "limit": limit})],
                   empty_reason="no_memory_yet")


RUN_REQUESTS_SQL = """
SELECT r.id, r.kind, r.fixture_id, r.requested_at, r.status, r.picked_at, r.cycle_id, c.finished_at, c.status AS cycle_status,
       c.counts, c.cost_usd, c.error
  FROM ai.run_requests r LEFT JOIN ai.cycles c ON c.id = r.cycle_id
 ORDER BY r.requested_at DESC, r.id DESC LIMIT 30
"""


def run_requests(conn: Conn) -> Envelope[list[dict[str, Any]]]:
    rows = []
    for r in fetch_all(conn, RUN_REQUESTS_SQL):
        rows.append({k: (v.isoformat() if isinstance(v, datetime) else float(v) if isinstance(v, Decimal) else v)
                     for k, v in r.items()})
    return listing(rows, empty_reason="no_run_requests")


def request_run(body: RunIn, *, user_id: int) -> RunQueued:
    with write_connection() as conn, conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT count(*) FROM ai.run_requests WHERE status IN ('queued', 'running')")
        pending = cur.fetchone()
        if pending is not None and int(pending[0]) >= 5:
            raise ApiError(409, "conflict", "five requests are already waiting for the worker")
        cur.execute("INSERT INTO ai.run_requests (kind, fixture_id, requested_at, requested_by) VALUES (%s, %s, %s, %s) "
                    "RETURNING id, kind, status, requested_at", (body.kind, body.fixture_id, now(), user_id))
        row = cur.fetchone()
    assert row is not None
    return RunQueued(id=int(row[0]), kind=str(row[1]), status=str(row[2]), requested_at=row[3])


# ── the Evolution dashboard ──────────────────────────────────────────────────

DASHBOARD_SQL = """
SELECT (SELECT count(DISTINCT fixture_id) FROM ai.match_packets WHERE built_at >= %(since)s AND built_at < %(until)s)
           AS matches_analyzed,
       (SELECT count(*) FROM ai.match_packets WHERE built_at >= %(since)s AND built_at < %(until)s) AS packets,
       (SELECT count(*) FROM ai.evidence WHERE retrieved_at >= %(since)s AND retrieved_at < %(until)s AND origin = 'web')
           AS news,
       (SELECT count(*) FROM ai.evidence WHERE retrieved_at >= %(since)s AND retrieved_at < %(until)s
          AND kind IN ('injury', 'suspension', 'doubtful')) AS injuries,
       (SELECT count(*) FROM ai.evidence WHERE retrieved_at >= %(since)s AND retrieved_at < %(until)s AND kind = 'lineup')
           AS lineups,
       (SELECT count(*) FROM ai.match_packets p, jsonb_array_elements(p.content->'market'->'selections') s
         WHERE p.built_at >= %(since)s AND p.built_at < %(until)s AND abs((s->>'movement')::float) >= 0.03) AS market_moves,
       (SELECT count(*) FROM ai.pick_reviews WHERE engine = 'combined' AND reviewed_at >= %(since)s
          AND reviewed_at < %(until)s) AS picks_evaluated,
       (SELECT count(*) FROM ai.pick_reviews WHERE engine = 'combined' AND decision = 'APPROVE'
          AND reviewed_at >= %(since)s AND reviewed_at < %(until)s) AS approved,
       (SELECT count(*) FROM ai.pick_reviews WHERE engine = 'combined' AND decision = 'DOWNGRADE'
          AND reviewed_at >= %(since)s AND reviewed_at < %(until)s) AS downgraded,
       (SELECT count(*) FROM ai.pick_reviews WHERE engine = 'combined' AND decision = 'REJECT'
          AND reviewed_at >= %(since)s AND reviewed_at < %(until)s) AS rejected,
       (SELECT count(*) FROM ai.pick_reviews WHERE engine = 'combined' AND decision = 'ABSTAIN'
          AND reviewed_at >= %(since)s AND reviewed_at < %(until)s) AS abstained,
       (SELECT count(*) FROM ai.pick_reviews WHERE engine = 'llm' AND reviewed_at >= %(since)s
          AND reviewed_at < %(until)s) AS llm_reviews,
       (SELECT count(*) FROM ai.postmortems WHERE created_at >= %(since)s AND created_at < %(until)s) AS postmortems,
       (SELECT count(*) FROM analytics.research_hypotheses WHERE created_at >= %(since)s AND created_at < %(until)s)
           AS hypotheses,
       (SELECT COALESCE(sum(cost_usd), 0) FROM ai.usage WHERE at >= %(since)s AND at < %(until)s) AS cost_usd
"""

UNREPORTED = "a regular starter was missing without any report"
"""What the match post-mortem (fbi.ai.postmortem) wrote, in English, for an absence nobody reported."""


def finding_text(r: dict[str, Any]) -> str | None:
    """A memory event's text as the owner reads it: the post-mortem's English for an unreported absence and the
    provider's English reason for a report that proved wrong (9 Oct 2026, "Guga (Fluminense): Missing Fixture -
    Inactive") said in Spanish; any other text through the same plain-words pass as the narratives."""
    text, ev = r.get("hypothesis"), r.get("evidence") or {}
    side = {"home": "local", "away": "visitante"}.get(str(ev.get("side")), "")
    if r.get("kind") == "news_signal" and text == UNREPORTED:
        who = ev.get("player") or (f"jugador {ev['player_id']}" if ev.get("player_id") else "")
        return "Un titular habitual faltó sin que nadie lo reportara" + (f": {who}" if who else "") + \
            (f" ({side})" if side and who else "") + "."
    if r.get("kind") == "context_error" and text:
        who = text.split(": ", 1)[0] if ev.get("tier") == "provider" and ": " in text else text
        return f"Reportado fuera y fue titular: {who}."
    return owner_text(text)


FINDINGS_SQL = """
SELECT id, created_at, kind, entity_type, entity_id, fixture_id, hypothesis, evidence, result, confidence, version
  FROM ai.memory_events
 WHERE created_at >= %(since)s AND created_at < %(until)s
   AND kind IN ('context_error', 'model_failure', 'model_success', 'league_pattern', 'team_pattern', 'player_pattern',
                'market_signal', 'news_signal')
 ORDER BY created_at DESC, id DESC LIMIT 30
"""

ERRORS_SQL = """
SELECT pm.fixture_id, th.name || ' - ' || ta.name AS match, f.kickoff_at, pm.outcome, sel AS selection, pm.narrative
  FROM ai.postmortems pm JOIN core.fixtures f ON f.id = pm.fixture_id
  JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id,
       jsonb_array_elements(pm.expected->'selections') sel
 WHERE pm.created_at >= %(since)s AND pm.created_at < %(until)s
   AND ((sel->>'decision' = 'APPROVE' AND sel->>'settled' = 'loss') OR (sel->>'decision' = 'REJECT'
        AND sel->>'settled' = 'win'))
 ORDER BY f.kickoff_at DESC LIMIT 30
"""


def dashboard(conn: Conn, *, day: date | None = None) -> Envelope[EvolutionDashboard]:
    d = day or now().astimezone(DAY_TZ).date()
    since = datetime.combine(d, time(0), tzinfo=DAY_TZ)
    until = since + timedelta(days=1)
    counts = fetch_one(conn, DASHBOARD_SQL, {"since": since, "until": until}) or {}
    cost = Decimal(counts.pop("cost_usd", 0) or 0)
    v2 = ai_v2.day_counts(conn, day=d)
    v2.pop("cost", None)
    errors = []
    for r in fetch_all(conn, ERRORS_SQL, {"since": since, "until": until}):
        s = r["selection"] or {}
        errors.append({"fixture_id": r["fixture_id"], "match": r["match"], "kickoff_at": r["kickoff_at"].isoformat(),
                       "score": (r["outcome"] or {}).get("score"), "market": s.get("market"),
                       "selection": s.get("selection"), "line": s.get("line"), "decision": s.get("decision"),
                       "settled": s.get("settled"), "p_model": s.get("p_model"), "p_market": s.get("p_market"),
                       "signals": s.get("signals") or [], "narrative": owner_text(r["narrative"])})
    return ok(EvolutionDashboard(
        day=d, counts={k: int(v or 0) for k, v in counts.items()} | v2,
        findings=[MemoryEvent.model_validate(r | {"hypothesis": finding_text(r)})
                  for r in fetch_all(conn, FINDINGS_SQL, {"since": since, "until": until})],
        errors=errors, shadow=[_shadow_row(r) for r in ai_shadow.latest(conn)], cost_usd=cost,
        learned=ai_v2.notes_learned_on(conn, d), proposals=ai_v2.proposals(conn)))
