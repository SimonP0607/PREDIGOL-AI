"""The AI decision layer over HTTP. Reading only, except the owner's queued "run now".

* ``GET /matches/{fixture_id}/analysis`` (product) - the match's PrediGol analysis, at most three cards,
  computed once by the worker and read by every user (200 readers are not 200 model calls). ``preview=shadow``
  shows the evaluation cards, SUPER_ADMIN only.
* ``/admin/ai/...`` (Admin Console) - overview, reviews with their full audit trail, packets, evidence,
  costs and the simulation, the AI's shadow report, its memory, and run requests.

No route here calls a language model and none can change a pick, a rule or a model.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

import psycopg
from fastapi import APIRouter, Depends, Path, Query

from fbi.api.contracts.ai_agents import AgentsOverview, MatchState
from fbi.api.contracts.ai_layer import (
    AiComparison,
    AiLearning,
    AiOverview,
    AiToday,
    DailyReview,
    DailyReviewDay,
    EvidenceRow,
    MatchAnalysis,
    MemoryEvent,
    PacketView,
    PickPostmortemRow,
    ResearchRow,
    ReviewDetail,
    ReviewRow,
    RunIn,
    RunQueued,
    SourceRow,
)
from fbi.api.contracts.ai_research import ResearchOverview
from fbi.api.contracts.ai_shadow import AgentRuns, Contradictions, ShadowArms, ShadowFile
from fbi.api.deps import get_db
from fbi.api.envelope import Envelope, ok
from fbi.api.errors import ApiError
from fbi.api.security import Admin, App
from fbi.api.services import (
    ai_agents,
    ai_layer,
    ai_research,
    ai_shadow,
    ai_v2,
    daily_review,
    match_memory,
)
from fbi.api.services.match_memory import MatchMemory, MemoryFilters
from fbi.auth.roles import Permission
from fbi.auth.service import Principal

router = APIRouter(tags=["predigol analysis"])
admin_router = APIRouter(tags=["admin: ai decision layer"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]
FixtureId = Annotated[int, Path(ge=1, le=2**62)]
Engine = Literal["rules", "llm", "combined", "ma-v1", "ma-v1-h", "cs-v1"]
"""The engines of ``ai.pick_reviews.engine`` the Console can ask for. ``rules``, ``llm`` and ``combined`` are production's: the decision layer reads
``combined`` (and ``rules``). ``ma-v1`` (MULTIAGENTE), ``ma-v1-h`` (MULTIAGENTE + COUNCIL HAIKU) and ``cs-v1`` (COUNCIL SOLO) are the SHADOW engines of
plan IA phase 3: their rows are written for the evaluation and never reach the decision layer or a user; they are listed only when asked for by name."""
DecisionQ = Literal["APPROVE", "DOWNGRADE", "REJECT", "ABSTAIN"]
EvidenceStatus = Literal["CONFIRMED", "PROBABLE", "RUMOR", "CONTRADICTORY", "OUTDATED"]
MemoryKind = Literal["match_result", "pick_result", "context_error", "news_signal", "injury_signal", "market_signal",
                     "model_failure", "model_success", "league_pattern", "team_pattern", "player_pattern",
                     "review_quality", "pick_postmortem"]
Verdict = Literal["approved_won", "approved_lost", "caution_won", "caution_lost", "rejected_would_have_won",
                  "rejected_correctly", "unreviewed_won", "unreviewed_lost", "push"]
LossClass = Literal["MODEL_ERROR", "CONTEXT_ERROR", "DATA_ERROR", "MARKET_ERROR", "EXECUTION_ERROR", "NORMAL_VARIANCE",
                    "UNKNOWN"]
Day = Annotated[date | None, Query(description="A Bogotá day (default: today, or yesterday for what was learned).")]
Preview = Annotated[Literal["shadow"] | None, Query(
    description="SUPER_ADMIN only: every card, the evaluation ones included. Never a user's view.")]


def _evaluation(preview: str | None, principal: Principal) -> bool:
    if preview is None:
        return False
    if not principal.can(Permission.SHADOW_PREVIEW):
        raise ApiError(403, "forbidden", "the evaluation view is for the Admin Console only")
    return True


@router.get("/matches/{fixture_id}/analysis", response_model=Envelope[MatchAnalysis | None])
def get_match_analysis(conn: Db, principal: App, fixture_id: FixtureId,
                       preview: Preview = None) -> Envelope[MatchAnalysis | None]:
    """ANÁLISIS PREDIGOL: up to three cards (market, selection, price, best bookmaker, model and market
    probabilities, fair and minimum odds, edge, the review's verdict, confidence, main reason and risks). Without
    an observed price the card says so and never calls it value."""
    return ai_layer.match_analysis(conn, fixture_id, evaluation=_evaluation(preview, principal))


@admin_router.get("/ai/overview", response_model=Envelope[AiOverview])
def get_overview(conn: Db) -> Envelope[AiOverview]:
    """Mode (off/shadow/enforce), configured tiers (never a key), budget and its state, whether enforcement is
    on (it needs the owner's switch AND a passed shadow gate), the last cycles and today's counts."""
    return ai_layer.overview(conn)


@admin_router.get("/ai/agents", response_model=Envelope[AgentsOverview])
def get_agents(conn: Db, days: Annotated[int, Query(ge=1, le=30)] = 7) -> Envelope[AgentsOverview]:
    """AGENTES (plan IA, phase 1): the registry as the code has it and every way it disagrees with the code, the engine each family of markets
    reads (the newest promotion row decides; none means the language model of today), what the job that writes the state of each match did in the
    last ``days`` (how many states, how big the slices against their cap, how long), the Orchestrator's queue and the nightly audit of what an agent
    may know. Reading only: it calls no model and creates no task."""
    return ai_agents.overview(conn, days=days)


@admin_router.get("/ai/matches/{fixture_id}/state", response_model=Envelope[MatchState])
def get_match_state(conn: Db, fixture_id: FixtureId) -> Envelope[MatchState]:
    """The state of a match (``ai.match_state``: the newest live row), the states it went through, newest first, and the tasks and attempts of the
    agents on it. A state keeps the measures of each slice of the package, never its content."""
    return ai_agents.match_state(conn, fixture_id)


@admin_router.get("/ai/reviews", response_model=Envelope[list[ReviewRow]])
def get_reviews(conn: Db, day: Annotated[date | None, Query()] = None, engine: Engine = "combined",
                decision: DecisionQ | None = None, fixture_id: Annotated[int | None, Query(ge=1, le=2**62)] = None,
                limit: Annotated[int, Query(ge=1, le=500)] = 200) -> Envelope[list[ReviewRow]]:
    """The reviews of a Bogotá day (default today) of ONE engine, newest first. ``engine`` defaults to ``combined``, the review the decision layer
    reads; the shadow engines (``ma-v1``, ``ma-v1-h``, ``cs-v1``) are listed only when asked for by name and never mixed with the others."""
    return ai_layer.reviews(conn, day=day, engine=engine, decision=decision, fixture_id=fixture_id, limit=limit)


@admin_router.get("/ai/reviews/{review_id}", response_model=Envelope[ReviewDetail])
def get_review(conn: Db, review_id: Annotated[int, Path(ge=1, le=2**62)]) -> Envelope[ReviewDetail]:
    """The whole audit trail: the structured output, every claim with its type and references, the evidence and
    its sources, the packet it read (hash and content), the engines combined, and each call's tokens and cost."""
    return ai_layer.review_detail(conn, review_id)


@admin_router.get("/ai/packets/{fixture_id}", response_model=Envelope[PacketView | None])
def get_packet(conn: Db, fixture_id: FixtureId) -> Envelope[PacketView | None]:
    """The newest AI_MATCH_PACKET of a fixture (immutable, hashed, every item with its source) and its history."""
    return ai_layer.packet(conn, fixture_id)


@admin_router.get("/ai/evidence", response_model=Envelope[list[EvidenceRow]])
def get_evidence(conn: Db, fixture_id: Annotated[int | None, Query(ge=1, le=2**62)] = None,
                 status: EvidenceStatus | None = None,
                 limit: Annotated[int, Query(ge=1, le=500)] = 200) -> Envelope[list[EvidenceRow]]:
    """News, injuries, line-ups: CONFIRMED / PROBABLE / RUMOR / CONTRADICTORY / OUTDATED, with the source, its
    tier, the dates and every status change."""
    return ai_layer.evidence(conn, fixture_id=fixture_id, status=status, limit=limit)


@admin_router.get("/ai/costs", response_model=Envelope[dict[str, Any]])
def get_costs(conn: Db) -> Envelope[dict[str, Any]]:
    """Measured spend (today, 7 and 30 days, the month; by purpose and model; per match, review and approved
    analysis), the budget, and the simulation of each provider profile on the platform's own volumes."""
    return ai_layer.cost_summary(conn)


@admin_router.get("/ai/shadow", response_model=Envelope[list[dict[str, Any]]])
def get_shadow(conn: Db) -> Envelope[list[dict[str, Any]]]:
    """Model alone vs model + AI vs the market, per engine, and the gate that decides whether the AI may ever
    filter what users see."""
    return ai_layer.shadow_reports(conn)


@admin_router.get("/ai/memory", response_model=Envelope[list[MemoryEvent]])
def get_memory(conn: Db, kind: MemoryKind | None = None,
               limit: Annotated[int, Query(ge=1, le=500)] = 200) -> Envelope[list[MemoryEvent]]:
    return ai_layer.memory(conn, kind=kind, limit=limit)


@admin_router.get("/ai/today", response_model=Envelope[AiToday])
def get_today(conn: Db, day: Day = None) -> Envelope[AiToday]:
    """HOY: today's matches with a market (Bogotá), each with its passes (first, pre, final), its L1 brief, its
    candidates and their decisions, and what it cost; the day's plan and budget."""
    return ai_v2.today_view(conn, day=day)


@admin_router.get("/ai/research", response_model=Envelope[list[ResearchRow]])
def get_research(conn: Db, day: Day = None) -> Envelope[list[ResearchRow]]:
    """INVESTIGACIONES: per match, the searches (when, cost, outcome) and the evidence with its source, link, dates,
    level, status, first and last seen."""
    return ai_v2.research(conn, day=day)


@admin_router.get("/ai/research/entities", response_model=Envelope[ResearchOverview])
def get_research_entities(conn: Db, days: Annotated[int, Query(ge=1, le=30)] = 7) -> Envelope[ResearchOverview]:
    """INVESTIGACIÓN POR ENTIDAD Y TEMA (plan IA, phase 2): the mode of research v2 and the evidence behind it, how fresh the answer kept for each topic is
    and how often it was reused instead of searched again, the answers kept entity by entity, the typed claims by class of source and by status, what
    each day's passes needed, paid, borrowed and reused, the Exa spend of v1 and of v2, v1 against v2 over the window and the gate evaluated now.
    Reading only: it searches nothing, calls no model and records no verdict."""
    return ai_research.overview(conn, days=days)


@admin_router.get("/ai/postmortems", response_model=Envelope[list[PickPostmortemRow]])
def get_postmortems(conn: Db, day: Day = None, verdict: Verdict | None = None,
                    classification: LossClass | None = None,
                    limit: Annotated[int, Query(ge=1, le=500)] = 200,
                    fixture_id: Annotated[int | None, Query(ge=1)] = None) -> Envelope[list[PickPostmortemRow]]:
    """POST-MORTEMS of a day's selections (default yesterday): the ten questions, the class of a loss, the
    narrative. ``fixture_id``: one match's, whatever its day."""
    return ai_v2.postmortems(conn, day=day, verdict=verdict, classification=classification, limit=limit,
                             fixture_id=fixture_id)


@admin_router.get("/ai/learning", response_model=Envelope[AiLearning])
def get_learning(conn: Db, day: Day = None) -> Envelope[AiLearning]:
    """APRENDIZAJE: what a day's results taught (default yesterday's, learned this morning) and the improvements
    proposed, awaiting the owner. Nothing here changes a model or a rule."""
    return ai_v2.learning(conn, day=day)


@admin_router.get("/ai/daily-reviews", response_model=Envelope[list[DailyReviewDay]])
def get_daily_reviews(conn: Db, days: Annotated[int, Query(ge=1, le=120)] = 30) -> Envelope[list[DailyReviewDay]]:
    """CIERRE DEL DÍA, the history: every closed Bogotá day of the last ``days``, its newest revision's numbers."""
    return daily_review.history(conn, days=days)


@admin_router.get("/ai/daily-reviews/{day}", response_model=Envelope[DailyReview | None])
def get_daily_review(conn: Db, day: Annotated[date, Path()]) -> Envelope[DailyReview | None]:
    """CIERRE DEL DÍA of one Bogotá day: its newest revision (written at 23:59, revised while a late match settled or
    its post-mortems arrived) and the revisions it went through."""
    return daily_review.day_review(conn, day=day)


@admin_router.get("/ai/match-memory", response_model=Envelope[list[MatchMemory]])
def get_match_memory(
    conn: Db,
    team: Annotated[str | None, Query(max_length=80)] = None,
    competition: Annotated[str | None, Query(max_length=80)] = None,
    coach: Annotated[str | None, Query(max_length=80)] = None,
    player: Annotated[str | None, Query(max_length=80)] = None,
    market: Annotated[Literal["1X2", "OU", "BTTS", "AH", "DC"] | None, Query()] = None,
    odds_band: Annotated[Literal["1.20-1.49", "1.50-1.79", "1.80-2.19", "2.20-2.99", "3.00-4.99", "5.00+"] | None,
                         Query()] = None,
    model: Annotated[Literal["dixon_coles", "poisson", "elo_ologit"] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Envelope[list[MatchMemory]]:
    """MATCH INTELLIGENCE MEMORY: the matches PrediGol looked at - what the AI and the models said before, what
    happened and what the post-mortems concluded after - by team, league, coach, player, market, odds band, model."""
    return match_memory.search(conn, MemoryFilters(team=team, competition=competition, coach=coach, player=player,
                                                   market=market, odds_band=odds_band, model=model), limit=limit)


@admin_router.get("/ai/sources", response_model=Envelope[list[SourceRow]])
def get_sources(conn: Db, days: Annotated[int, Query(ge=1, le=60)] = 7) -> Envelope[list[SourceRow]]:
    """FUENTES: per domain - how often it came up, useful and discarded evidence, cost, utility rate."""
    return ai_v2.sources(conn, days=days)


@admin_router.get("/ai/comparison", response_model=Envelope[AiComparison])
def get_comparison(conn: Db) -> Envelope[AiComparison]:
    """MODELO SOLO / MODELO + REGLAS / MODELO + IA / MERCADO on the same settled selections (shadow)."""
    return ai_v2.comparison(conn)


@admin_router.get("/ai/run-requests", response_model=Envelope[list[dict[str, Any]]])
def get_run_requests(conn: Db) -> Envelope[list[dict[str, Any]]]:
    return ai_layer.run_requests(conn)


@admin_router.post("/ai/run-requests", response_model=Envelope[RunQueued])
def post_run_request(body: RunIn, principal: Admin) -> Envelope[RunQueued]:
    """Queue an analysis (of one fixture, or of the day) or a learning cycle; the worker runs it within two minutes
    under the same budget and caps. At most five requests wait at once."""
    return ok(ai_layer.request_run(body, user_id=principal.user_id))



# ── the shadow of phase 3 (plan IA): the arms, the contradictions, the runs of the agents, the file of a match. Reading only. ──────────────────────

ContraQ = Literal["C01", "C02", "C03", "C04", "C05", "C06", "C07", "C08"]
AgentQ = Literal["match", "council", "stats", "brief", "reviewer", "extractor", "postmortem", "post_match_reviewer", "learning_analyst",
                 "claim_extractor"]
TaskQ = Literal["context", "evaluation", "extraction", "narrative", "council", "analyst", "loss_review", "escalation", "owner_research",
                "review_analysis", "review_final"]
RunStatusQ = Literal["ok", "invalid", "timeout", "abstain", "skipped", "expired", "budget_skip"]
RunKindQ = Literal["live", "shadow", "replay", "battery"]
PassQ = Literal["first", "pre", "final", "request"]


@admin_router.get("/ai/shadow/arms", response_model=Envelope[ShadowArms])
def get_shadow_arms(conn: Db, days: Annotated[int, Query(ge=1, le=90)] = ai_shadow.WINDOW_DAYS) -> Envelope[ShadowArms]:
    """SOMBRA CON BRAZOS (plan IA, section 22): the seven arms over the last ``days`` days - reviews and selections, the share approved, downgraded,
    rejected and abstained, invalid outputs, cost (LAB, from the ledger), p95 latency, pause reasons -, how the matches were assigned, and the plan's
    thresholds (30 days, 300 selections) as counts. It never says an arm passed: reaching a threshold only says there is enough to look."""
    return ai_shadow.shadow_arms(conn, days=days)


@admin_router.get("/ai/contradictions", response_model=Envelope[Contradictions])
def get_contradictions(conn: Db, days: Annotated[int, Query(ge=1, le=60)] = 7, code: ContraQ | None = None,
                       limit: Annotated[int, Query(ge=1, le=200)] = 50) -> Envelope[Contradictions]:
    """CONTRADICCIONES (plan IA, sections 11 and 33): C01-C08 written by ``contra-v1`` in the shadow over the last ``days`` days - how many of each,
    in how many passes and matches, how many rest on confirmed evidence, what each engine's Council did with the candidates they touch (kept,
    lowered, abstained, none) - and the most recent ones (``code`` filters them) with their candidates and references."""
    return ai_shadow.contradictions(conn, days=days, code_=code, limit=limit)


@admin_router.get("/ai/agent-runs", response_model=Envelope[AgentRuns])
def get_agent_runs(conn: Db, day: Day = None, agent: AgentQ | None = None, task_kind: TaskQ | None = None, status: RunStatusQ | None = None,
                   model: Annotated[str | None, Query(max_length=64, pattern=r"^[A-Za-z0-9._-]+$")] = None,
                   run_kind: RunKindQ | None = "shadow", fixture_id: Annotated[int | None, Query(ge=1, le=2**62)] = None,
                   limit: Annotated[int, Query(ge=1, le=500)] = 100) -> Envelope[AgentRuns]:
    """EJECUCIONES DE LOS AGENTES: the attempts of ``ai.agent_runs`` of a Bogotá day (default today), newest first - agent, task, model, status, tokens,
    cost, latency, the rule of ``router-v1`` that escalated it - with filters, and the day's Opus calls against the shadow's cap of 3."""
    return ai_shadow.agent_runs(conn, day=day, agent=agent, task_kind=task_kind, status=status, model=model, run_kind=run_kind,
                                fixture_id=fixture_id, limit=limit)


@admin_router.get("/ai/matches/{fixture_id}/shadow", response_model=Envelope[ShadowFile])
def get_match_shadow(conn: Db, fixture_id: FixtureId, pass_kind: PassQ | None = None) -> Envelope[ShadowFile]:
    """EXPEDIENTE of a match for the shadow: its assignment, the candidates the server named (c1..cN) with its numbers, the Match Agent's assessments
    and the contradictions in codes, every engine's verdict on every candidate beside today's reviewers', the evidence ids cited and the calls with their
    cost. Codes only: no free text of a model, no address."""
    return ai_shadow.shadow_file(conn, fixture_id, pass_kind=pass_kind)
