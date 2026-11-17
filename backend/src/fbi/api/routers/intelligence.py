"""PrediGol Intelligence over HTTP (Admin Console, SUPER_ADMIN): the day, the decisions and their full record, the match
dossier and narrative, calibration and its gates, memory, the daily learning reports, the market registry, the runs
with the leakage audit, and the costs. Reading only: nothing here can change a decision, a pick, a model or a rule."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

import psycopg
from fastapi import APIRouter, Depends, Path, Query

from fbi.api.contracts.intelligence.alerts import AlertsContract
from fbi.api.contracts.intelligence.console import ConsoleContract
from fbi.api.contracts.intelligence.match import MatchIntelligencePrivate
from fbi.api.contracts.intelligence.match_v2 import MatchIntelligenceV2Private
from fbi.api.contracts.intelligence.parlays import ParlaySetStatePrivate
from fbi.api.contracts.intelligence.post_evaluation import PostMatchEvaluation
from fbi.api.contracts.intelligence.tracking import Tracking
from fbi.api.deps import get_db
from fbi.api.envelope import Envelope, ok
from fbi.api.services import capabilities as capabilities_svc
from fbi.api.services import families as families_svc
from fbi.api.services import intelligence as svc
from fbi.api.services import intelligence_alerts as alerts_svc
from fbi.api.services import intelligence_console as console_svc
from fbi.api.services import match_intelligence, match_intelligence_v2
from fbi.api.services import parlay_states as parlay_states_svc
from fbi.api.services import post_evaluation as post_evaluation_svc
from fbi.api.services import product as product_svc
from fbi.api.services import tracking as tracking_svc
from fbi.lifecycle.machine import State as LifecycleState

router = APIRouter(tags=["admin: predigol intelligence"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]
Day = Annotated[date | None, Query(description="A Bogotá day (default: today).")]
State = Literal["RECHAZADO", "INVESTIGACION", "CAUTELA", "APROBADO", "PICK_DEL_DIA", "CANDIDATO_PARLAY", "PICK_PREMIUM"]
Market = Literal["1X2", "OU", "BTTS", "DC", "AH"]
EntityType = Literal["team", "player", "coach", "referee", "competition", "market"]
Family = Literal["GOALS_HALF", "CORNERS", "CARDS", "YELLOW"]
FamilyState = Literal["INVESTIGACION", "RECHAZADO"]


@router.get("/intelligence/day", response_model=Envelope[dict[str, Any]])
def get_day(conn: Db, day: Day = None) -> Envelope[dict[str, Any]]:
    """EL DÍA DE PREDIGOL INTELLIGENCE: analysed, candidates by state and context, depth, cost and tokens, sources,
    the picks of the day (v6 shadow beside v5), the calibration behind them and the day's learning report."""
    return svc.day_view(conn, day=day)


@router.get("/intelligence/decisions", response_model=Envelope[dict[str, Any]])
def get_decisions(conn: Db, day: Day = None, state: State | None = None, market: Market | None = None,
                  fixture_id: Annotated[int | None, Query(ge=1, le=2**62)] = None,
                  limit: Annotated[int, Query(ge=1, le=1000)] = 300) -> Envelope[dict[str, Any]]:
    """The newest decision of every selection of the day's matches, filtered."""
    return svc.decisions(conn, day=day, state=state, market=market, fixture_id=fixture_id, limit=limit)


@router.get("/intelligence/decisions/{decision_id}", response_model=Envelope[dict[str, Any]])
def get_decision(conn: Db, decision_id: Annotated[int, Path(ge=1, le=2**62)]) -> Envelope[dict[str, Any]]:
    """One decision whole: the model and its version, the calibrator, the market, price and bookmaker, the ten
    filters, the score and the stake with their components, the AI's review and the evidence, the outcome, the
    post-mortem and the selection's history - and, under ``intelligence``, contract C-02 «Selección» in its private
    projection (AD-J03, IA-114: why, against, what it depends on, how it settles, versions, sources, the market's
    validation, the cycle's state and the price with its age). Every key it had before is unchanged."""
    return svc.decision_detail(conn, decision_id)


@router.get("/intelligence/matches", response_model=Envelope[dict[str, Any]])
def get_matches(conn: Db, day: Day = None, q: Annotated[str | None, Query(min_length=1, max_length=60)] = None,
                limit: Annotated[int, Query(ge=1, le=100)] = 40) -> Envelope[dict[str, Any]]:
    """THE PICKER OF THE DOSSIER: the matches of a Bogotá day (the ones the AI studied first), or, with a text, the matches of the
    teams or competitions it names within 45 days of the day - a number is also looked up as a match id - each with whether the AI
    has a packet for it and how much research its latest brief asked for."""
    return svc.matches(conn, q=q, day=day, limit=limit)


@router.get("/intelligence/matches/{fixture_id}/dossier", response_model=Envelope[dict[str, Any]])
def get_dossier(conn: Db, fixture_id: Annotated[int, Path(ge=1, le=2**62)]) -> Envelope[dict[str, Any]]:
    """The match's MATCH INTELLIGENCE PACKAGE (dossier-v3), the weighted head-to-head, the scenarios, the status of the context
    factors the AI saw, its narrative, its latest brief (what it asked the server to look into and every claim the server refused),
    the passes that ran and its decisions."""
    return svc.dossier(conn, fixture_id)


@router.get("/intelligence/matches/{fixture_id}/intelligence", response_model=Envelope[MatchIntelligencePrivate])
def get_match_intelligence(conn: Db, fixture_id: Annotated[int, Path(ge=1, le=2**62)]
                           ) -> Envelope[MatchIntelligencePrivate]:
    """C-01, the match's contract, PRIVATE projection (AD-J02, IA-066): the public one and what only the owner sees - every
    selection with the decision layer's shadow state and numbers, the model's own figure (sin_calibrar), the AI's brief,
    the chronicle whatever its switch and every stored item of evidence. The untyped dossier above stays as it is."""
    return match_intelligence.private(conn, fixture_id)


@router.get("/intelligence/matches/{fixture_id}/intelligence/v2", response_model=Envelope[MatchIntelligenceV2Private])
def get_match_intelligence_v2(conn: Db, fixture_id: Annotated[int, Path(ge=1, le=2**62)]
                              ) -> Envelope[MatchIntelligenceV2Private]:
    """C-01 2.0.0, PRIVATE projection (AD-J02 delivery 2, IA-131): the public one and the shadow of every block - the scenarios
    (scenarios-v2), the one chronicle and its update after the line-up (chronicle-v4), E1-E4 with their verdicts, the C-07 sources
    embedded, the C-05 alerts of the match, each selection's state in the cycle (C-02) and the players' forecasts
    (player-engine-v2). The 1.x route above keeps its shape."""
    return match_intelligence_v2.private(conn, fixture_id)


@router.get("/intelligence/factors", response_model=Envelope[dict[str, Any]])
def get_factors(conn: Db) -> Envelope[dict[str, Any]]:
    """The registry of context factors as it stands: each factor, what an experiment would have to show, its status
    (DESCRIPTIVE until a person validates it with an experiment) and the decisions behind it."""
    return svc.factors(conn)


@router.get("/intelligence/calibration", response_model=Envelope[dict[str, Any]])
def get_calibration(conn: Db) -> Envelope[dict[str, Any]]:
    """Champions and challengers per (market, model), the gates fixed in advance, every promotion and retirement, the
    prospective evaluations."""
    return svc.calibration(conn)


@router.get("/intelligence/memory", response_model=Envelope[dict[str, Any]])
def get_memory(conn: Db, entity_type: EntityType | None = None,
               q: Annotated[str | None, Query(max_length=80)] = None,
               aspect: Annotated[str | None, Query(max_length=60)] = None,
               limit: Annotated[int, Query(ge=1, le=500)] = 100) -> Envelope[dict[str, Any]]:
    return svc.memory(conn, entity_type=entity_type, q=q, limit=limit, aspect=aspect)


@router.get("/intelligence/memory/{entity_type}/{entity_id}", response_model=Envelope[dict[str, Any]])
def get_memory_history(conn: Db, entity_type: EntityType,
                       entity_id: Annotated[str, Path(max_length=120)]) -> Envelope[dict[str, Any]]:
    return svc.memory_history(conn, entity_type, entity_id)


@router.get("/intelligence/reports", response_model=Envelope[dict[str, Any]])
def get_reports(conn: Db, day: Day = None) -> Envelope[dict[str, Any]]:
    """The DAILY LEARNING REPORT of a day (its newest revision) and the days that have one."""
    return svc.reports(conn, day=day)


@router.get("/intelligence/markets", response_model=Envelope[dict[str, Any]])
def get_markets(conn: Db) -> Envelope[dict[str, Any]]:
    """MARKET DISCOVERY ENGINE: every pre-match market of the provider with its ten criteria and status."""
    return svc.markets(conn)


@router.get("/intelligence/market-matrix", response_model=Envelope[dict[str, Any]])
def get_market_matrix(conn: Db) -> Envelope[dict[str, Any]]:
    """THE MATRIX OF MARKETS BY FAMILY (plan F9): for each kind of bet, what is priced, what can be graded and the verdict. Reads the
    newest stored matrix; building one is the weekly job's work."""
    return svc.market_matrix(conn)


@router.get("/intelligence/families", response_model=Envelope[dict[str, Any]])
def get_families(conn: Db, family: Family | None = None, state: FamilyState | None = None,
                 days: Annotated[int, Query(ge=1, le=families_svc.MAX_DAYS)] = families_svc.DEFAULT_DAYS,
                 limit: Annotated[int, Query(ge=1, le=500)] = 200) -> Envelope[dict[str, Any]]:
    """THE FAMILIES IN SHADOW (plan F10.17 and F11.11): corners, cards and the goals of the halves decide without being believed. The last word of
    each family's model on each market of the matches of the window, the rule that grades each bet, what became of it, the post-mortem the
    families made of it and what they remember. Reading only; empty while the switch of the families is off."""
    return families_svc.overview(conn, family=family, state=state, days=days, limit=limit)


@router.get("/intelligence/price-clock", response_model=Envelope[dict[str, Any]])
def get_price_clock(conn: Db) -> Envelope[dict[str, Any]]:
    """THE PRICE CLOCK: the provider's markets structured from the RAW /odds payloads (plan F1) - what is read, what waits,
    what it weighs and what went wrong."""
    return svc.price_clock(conn)


@router.get("/intelligence/runs", response_model=Envelope[dict[str, Any]])
def get_runs(conn: Db, limit: Annotated[int, Query(ge=1, le=500)] = 60) -> Envelope[dict[str, Any]]:
    """The jobs' record (duration, status, counts, errors, version) and the latest data-leakage audit."""
    return svc.runs(conn, limit=limit)


@router.get("/intelligence/costs", response_model=Envelope[dict[str, Any]])
def get_costs(conn: Db) -> Envelope[dict[str, Any]]:
    """Cost per match, candidate, pick, research and post-mortem, per day, and the month against the budget."""
    return svc.costs(conn)


@router.get("/intelligence/capabilities", response_model=Envelope[dict[str, Any]])
def get_capabilities(conn: Db) -> Envelope[dict[str, Any]]:
    """THE REGISTRY OF CAPABILITIES (IA-056, AD-003): every capability of the plan with its state (construida, en_sombra,
    lista_para_revision, autorizada), its safety and validation verdicts with evidence and sample, the newest rows of the gates it
    answers to and its agents' runs of the last seven days. Reading only: the registry switches nothing."""
    return capabilities_svc.overview(conn)


@router.get("/intelligence/alerts", response_model=Envelope[AlertsContract])
def get_alerts(conn: Db, hours: Annotated[int, Query(ge=1, le=720)] = 48,
               fixture_id: Annotated[int | None, Query(ge=1, le=2**62)] = None,
               kind: Literal["retirada", "sin_alineacion", "cambio_horario", "cambio_condiciones"] | None = None) -> Envelope[AlertsContract]:
    """THE OWNER'S PRIVATE ALERTS, contract C-05 (IA-107, AD-D08): what the evaluation cycle (eval-cycle-v1, in the shadow) withdrew, the
    line-ups that did not arrive in time and the changes of kick-off or conditions, each «antes -> ahora», newest first. Reading only: it
    notifies nobody, and nothing a reader sees comes from here."""
    return alerts_svc.alerts(conn, hours=hours, fixture_id=fixture_id, kind=kind)


@router.get("/intelligence/console", response_model=Envelope[ConsoleContract])
def get_console(conn: Db) -> Envelope[ConsoleContract]:
    """THE INTELLIGENCE CONSOLE, contract C-11 (IA-079, AD-J08): «nada sale de la sombra» (FBI_PICKS_SOURCE, FBI_AI_MODE and the switches of
    Intelligence, as they read), the registry of capabilities with their state and verdicts, the costs against their envelopes and the joint
    ceiling, the safety controls (the newest battery, the leakage audit, the gates with their real verdict, the schema) and the news engine and
    the private alerts' queue as absent with their reason. Reading only: it shows every switch and changes none."""
    return console_svc.console(conn)


TrackingFamily = Literal["core", "corners", "cards", "goals_halves"]


@router.get("/intelligence/tracking", response_model=Envelope[Tracking])
def get_tracking(conn: Db, state: LifecycleState | None = None, family: TrackingFamily | None = None,
                 competition: Annotated[int | None, Query(ge=1, le=2**62)] = None,
                 date_from: Annotated[date | None, Query(alias="from", description="First Bogotá day of kick-off.")] = None,
                 date_to: Annotated[date | None, Query(alias="to", description="Last Bogotá day of kick-off (31 days at most).")] = None,
                 cursor: Annotated[int | None, Query(ge=1, le=2**62)] = None,
                 limit: Annotated[int, Query(ge=1, le=200)] = 50) -> Envelope[Tracking]:
    """C-03 «Seguimiento privado» (AD-J04, IA-115): the selections in the shadow by state of the cycle (the ten states, zero included),
    the sample each family accumulates against the sample the validation board needs (AD-K02), and the selections themselves with their
    figure, price, evaluation step, result and CLV, filtered and paged by the server. Reading only."""
    return ok(tracking_svc.tracking(conn, date_from=date_from, date_to=date_to, state=state, family=family,
                                    competition_id=competition, cursor=cursor, limit=limit))


ParlayKind = Literal["daily", "multiday"]


@router.get("/intelligence/parlays", response_model=Envelope[ParlaySetStatePrivate])
def get_parlays(conn: Db, kind: ParlayKind | None = None,
                date_from: Annotated[date | None, Query(alias="from", description="First product day (Bogotá).")] = None,
                date_to: Annotated[date | None, Query(alias="to", description="Last product day (31 days at most).")] = None,
                ) -> Envelope[ParlaySetStatePrivate]:
    """C-04 «Parlays con estado», private projection (AD-J05, IA-132): the parlays of parlay-v6 kept in the shadow over the period (the
    last seven product days by default) with the state of each set, its legs and their results, the joint and its pessimistic end, the
    margin accumulated and why a day had none; beside them the product's parlays of now (parlay-v5, what a reader is shown) and
    parlay-v5's kept history by state. Reading only."""
    kinds: tuple[ParlayKind, ...] = (kind,) if kind else ("daily", "multiday")
    live = [product_svc.parlay_board(conn, k, include_shadow=False).data for k in kinds]
    return ok(parlay_states_svc.private(conn, live=live, kind=kind, date_from=date_from, date_to=date_to))


@router.get("/intelligence/evaluations/{fixture_id}", response_model=Envelope[PostMatchEvaluation])
def get_post_evaluation(conn: Db, fixture_id: Annotated[int, Path(ge=1, le=2**62)]) -> Envelope[PostMatchEvaluation]:
    """C-08 «Evaluación posterior» (AD-J07, IA-133): per settled selection of the match, what we anticipated, what happened, whether it
    was a good price, which evidence held or failed, whether the line-up changed anything and whether the scenario came true (absent until
    AD-B02), with the accumulated calibration of its market on the validation board and the notice «Un acierto no valida el mercado».
    Reading only."""
    return ok(post_evaluation_svc.evaluation(conn, fixture_id))
