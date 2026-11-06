/** TanStack Query option factories for the live API. */
import { infiniteQueryOptions } from "@tanstack/react-query";
import { filterParams, v1, type BestOddsQuery, type MatchQuery } from "./client";
import type { MyPicksFilter } from "./types_mypicks";
import type { FeedbackSubject } from "./types_feedback";
import type { ExplainIntent, SlipLegBody } from "./types_explain";
import type { ParlayKind, PicksQuery } from "./types_product";
import type { BuilderQuery } from "./types_builder";
import type { HistoryPeriod } from "./types_records";
import type { RatingPool } from "./types";
import type { FindingsQuery, ScoresQuery } from "./types_truth";
import type { MemoryFilters } from "./types_ai_layer";
import type { AgentRunsQuery, ContraCode } from "./types_ai_shadow";
import type { PairStatus } from "./types_referees";

export const AUDIT_PAGE = 100;
const MINUTE = 60_000;
type Preview = "shadow" | undefined;

export const live = {
  // ── auth ──────────────────────────────────────────────────────────────────
  me: { queryKey: ["auth", "me"], queryFn: v1.me, staleTime: 5 * MINUTE, retry: false },
  /** The reader's favourites (plan UX, A13): Home's own part follows them through /today. */
  favorites: { queryKey: ["me", "favorites"], queryFn: v1.myFavorites, staleTime: 5 * MINUTE },
  favoriteOptions: (q: string) => ({
    queryKey: ["me", "favorite-options", q],
    queryFn: () => v1.favoriteOptions(q),
    staleTime: 10 * MINUTE,
  }),
  /**
   * Help and support (plan UX, A14): the reader's tickets, the categories and the contact. Read again whenever Ayuda or a
   * message's page opens (staleTime 0): a ticket answered a moment ago never reads «Esperando respuesta» from the cache
   * (found by A16's journey: the receipt's «Ver mi mensaje» within a minute of the owner's answer).
   */
  support: { queryKey: ["me", "support"], queryFn: v1.mySupport, staleTime: 0 },
  /** Whether the monthly survey is owed (plan UX, B6): read once per visit; an answer or a skip reads it again. */
  survey: { queryKey: ["me", "feedback", "survey"], queryFn: v1.mySurvey, staleTime: 30 * MINUTE },
  /** The reader's «¿Te sirvió?» on one thing read. */
  helpfulVote: (subject: FeedbackSubject, subjectId: number) => ({
    queryKey: ["me", "feedback", "helpful", subject, subjectId],
    queryFn: () => v1.myHelpfulVote(subject, subjectId),
    staleTime: 30 * MINUTE,
  }),
  /**
   * The reader's notices on their devices (plan UX, B7): whether they can be offered at all, the key to subscribe with,
   * their devices and categories. Read again after any change of theirs.
   */
  push: { queryKey: ["me", "push"], queryFn: v1.myPush, staleTime: 5 * MINUTE },
  /** The bell of one match. */
  matchAlert: (fixtureId: number) => ({
    queryKey: ["me", "match-alert", fixtureId],
    queryFn: () => v1.myMatchAlert(fixtureId),
    staleTime: 5 * MINUTE,
  }),
  /** The newest entry of Novedades the reader has seen: «Más» marks a newer one. */
  updatesSeen: {
    queryKey: ["me", "updates", "seen"],
    queryFn: v1.myUpdatesSeen,
    staleTime: 30 * MINUTE,
  },
  /**
   * The account centre (plan UX, B1): what the profile's eight blocks say folded. Read again whenever the profile opens
   * (staleTime 0) and after a change in one of its blocks.
   */
  account: { queryKey: ["me", "account"], queryFn: v1.myAccount, staleTime: 0 },
  /**
   * What the reader's own use orders and suggests (plan UX, B2): their markets first in a match's «Mercados» and one league
   * or team to follow. Kept five minutes: their habits move slowly; a choice of theirs reads it again.
   */
  personal: { queryKey: ["me", "personal"], queryFn: v1.myPersonal, staleTime: 5 * MINUTE },
  /** Public: the way to reach PrediGol without signing in. */
  supportContact: {
    queryKey: ["support", "contact"],
    queryFn: v1.supportContact,
    staleTime: 30 * MINUTE,
    retry: false,
  },

  // ── product ───────────────────────────────────────────────────────────────
  home: (preview: Preview) => ({
    queryKey: ["v1", "home", preview ?? "qualified"],
    queryFn: () => v1.home({ preview }),
    refetchInterval: MINUTE,
  }),
  productPicks: (q: PicksQuery, preview: Preview) => ({
    queryKey: ["v1", "product-picks", q, preview ?? "qualified"],
    queryFn: () => v1.productPicks({ ...q, preview }),
    refetchInterval: 2 * MINUTE,
  }),
  startedPicks: (preview: Preview) => ({
    queryKey: ["v1", "started-picks", preview ?? "qualified"],
    queryFn: () => v1.startedPicks({ preview }),
    refetchInterval: MINUTE,
  }),
  /**
   * «¿Por qué este pick?» (plan UX, B3): asked for when the reader opens it (the sheet sets `enabled`); the same for every
   * reader, kept a minute - its price now moves, its reasons do not.
   */
  pickExplanation: (pickId: number, preview: Preview) => ({
    queryKey: ["v1", "pick-explanation", pickId, preview ?? "qualified"],
    queryFn: () => v1.pickExplanation(pickId, { preview }),
    staleTime: MINUTE,
    retry: false,
  }),
  /**
   * «Explícame» (plan UX, B9): asked for when the reader picks a question (the sheet sets `enabled`); the same answer for every
   * reader of a match or a pick, kept a minute.
   */
  explain: (entity: "match" | "pick", id: number, intent: ExplainIntent, preview: Preview) => ({
    queryKey: ["v1", "explain", entity, id, intent, preview ?? "qualified"],
    queryFn: () => v1.explain(entity, id, intent, { preview }),
    staleTime: MINUTE,
    retry: false,
  }),
  /** The parlay being built: keyed by its legs, so a leg added or removed asks again. */
  explainParlay: (legs: SlipLegBody[]) => ({
    queryKey: [
      "v1",
      "explain",
      "parlay",
      legs.map((l) => `${l.fixture_id}:${l.market_key}:${l.selection}:${l.line}`),
    ],
    queryFn: () => v1.explainParlay(legs),
    staleTime: MINUTE,
    retry: false,
  }),
  parlay: (kind: ParlayKind, preview: Preview) => ({
    queryKey: ["v1", "parlay", kind, preview ?? "qualified"],
    queryFn: () => v1.parlay(kind, { preview }),
    refetchInterval: 2 * MINUTE,
  }),
  /** Asked for by the user (the page sets `enabled`); the server keeps an answer 30 s. */
  builtParlay: (q: BuilderQuery, preview: Preview) => ({
    queryKey: ["v1", "built-parlay", q, preview ?? "qualified"],
    queryFn: () => v1.buildParlay({ ...q, preview }),
    staleTime: 30_000,
  }),
  bestOdds: (q: BestOddsQuery, preview: Preview) => ({
    queryKey: ["v1", "best-odds", q, preview ?? "qualified"],
    queryFn: () => v1.bestOdds({ ...q, preview }),
    refetchInterval: 2 * MINUTE,
  }),
  daily: (preview: Preview, day?: string) => ({
    queryKey: ["v1", "daily", day ?? "today", preview ?? "qualified"],
    queryFn: () => v1.daily({ day, preview }),
    refetchInterval: 2 * MINUTE,
  }),
  /** The first 500 saved picks: what the product needs to show a selection as saved (useSavedPicks). */
  myPicks: {
    queryKey: ["v1", "me", "picks"],
    queryFn: () => v1.myPicks(),
    refetchInterval: 2 * MINUTE,
  },
  /**
   * The saved picks a page at a time (plan UX, A1: "Todo" was cut at 500 and called everything): `size` per page,
   * the next page from `meta.next_cursor`. Mis picks lists with pages of 25 (parlays: 10); the recap reads every
   * page, of 500 (parlays: 200, the most the API serves).
   */
  /** The reader's saved picks a page at a time, under the filter of Mis picks when one is given (plan UX, B5). */
  myPicksPages: (size: number, filter?: MyPicksFilter) =>
    infiniteQueryOptions({
      queryKey: ["v1", "me", "picks", "pages", size, filterParams(filter)],
      queryFn: ({ pageParam }) => v1.myPicks({ limit: size, cursor: pageParam, filter }),
      initialPageParam: undefined as string | undefined,
      getNextPageParam: (last) => last.meta.next_cursor ?? undefined,
      refetchInterval: 2 * MINUTE,
    }),
  /** Totals, breakdown and line value of the reader's saved picks under the filter (plan UX, B5). */
  myPicksSummary: (filter?: MyPicksFilter) => ({
    queryKey: ["v1", "me", "picks", "summary", filterParams(filter)],
    queryFn: () => v1.myPicksSummary(filter),
    refetchInterval: 2 * MINUTE,
  }),
  myParlaysPages: (size: number) =>
    infiniteQueryOptions({
      queryKey: ["v1", "me", "parlays", "pages", size],
      queryFn: ({ pageParam }) => v1.myParlays({ limit: size, cursor: pageParam }),
      initialPageParam: undefined as string | undefined,
      getNextPageParam: (last) => last.meta.next_cursor ?? undefined,
      refetchInterval: 2 * MINUTE,
    }),
  history: (period: HistoryPeriod, preview: Preview) => ({
    queryKey: ["v1", "me", "history", period, preview ?? "qualified"],
    queryFn: () => v1.history(period, { preview }),
    refetchInterval: 2 * MINUTE,
  }),
  matchView: (id: string) => ({
    queryKey: ["v1", "match-view", id],
    queryFn: () => v1.matchView(id),
    refetchInterval: MINUTE,
  }),

  // ── football ──────────────────────────────────────────────────────────────
  standings: (id: string, season?: number) => ({
    queryKey: ["v1", "standings", id, season ?? "newest"],
    queryFn: () => v1.standings(id, season),
  }),
  competitionReference: (id: string, season?: number) => ({
    queryKey: ["v1", "competition-reference", id, season ?? "default"],
    queryFn: () => v1.competitionReference(id, season),
  }),
  providerPrediction: (id: string) => ({
    queryKey: ["v1", "admin", "provider-prediction", id],
    queryFn: () => v1.providerPrediction(id),
  }),
  center: (id: string) => ({
    queryKey: ["v1", "center", id],
    queryFn: () => v1.center(id),
    refetchInterval: 30_000,
  }),
  matchProfile: (id: string) => ({
    queryKey: ["v1", "match-profile", id],
    queryFn: () => v1.matchProfile(id),
    staleTime: 5 * MINUTE,
  }),
  matchMarkets: (id: string) => ({
    queryKey: ["v1", "match-markets", id],
    queryFn: () => v1.matchMarkets(id),
    refetchInterval: 2 * MINUTE,
  }),
  matchAnalysis: (id: string, preview: Preview) => ({
    queryKey: ["v1", "match-analysis", id, preview ?? "qualified"],
    queryFn: () => v1.matchAnalysis(id, { preview }),
    refetchInterval: 5 * MINUTE,
  }),
  matchForecast: (id: string, preview: Preview) => ({
    queryKey: ["v1", "match-forecast", id, preview ?? "user"],
    queryFn: () => v1.matchForecast(id, { preview }),
    refetchInterval: 5 * MINUTE,
  }),
  matchCalendar: (id: string, preview: Preview) => ({
    queryKey: ["v1", "match-calendar", id, preview ?? "user"],
    queryFn: () => v1.matchCalendar(id, { preview }),
    refetchInterval: 15 * MINUTE,
  }),
  /** A finished match does not change by the minute: the worker rebuilds it when its inputs change, a few times at most. */
  matchKnowledge: (id: string, preview: Preview) => ({
    queryKey: ["v1", "match-knowledge", id, preview ?? "user"],
    queryFn: () => v1.matchKnowledge(id, { preview }),
    refetchInterval: 10 * MINUTE,
  }),
  /**
   * A finished match's settlement and why (plan UX, B4): settled within minutes of the whistle, explained the night after;
   * the reader's own saved picks are in it, so it is read again when they come back.
   */
  matchPostmatch: (id: string, preview: Preview) => ({
    queryKey: ["v1", "match-postmatch", id, preview ?? "user"],
    queryFn: () => v1.matchPostmatch(id, { preview }),
    refetchInterval: 5 * MINUTE,
  }),
  /** The reading changes when PrediGol Intelligence stores a new packet (every one to three hours) or a new forecast. */
  matchReading: (id: string, preview: Preview) => ({
    queryKey: ["v1", "match-reading", id, preview ?? "user"],
    queryFn: () => v1.matchReading(id, { preview }),
    refetchInterval: 10 * MINUTE,
  }),
  /** Home's board: the server keeps it a minute; the page reads it again when the reader comes back to it. */
  today: { queryKey: ["v1", "today"], queryFn: v1.today, refetchInterval: 2 * MINUTE },
  /** Why the day has no pick, for the Picks page: the server keeps it five minutes. */
  noPick: { queryKey: ["v1", "today", "no-pick"], queryFn: v1.noPick, refetchInterval: 5 * MINUTE },
  /** «Cómo le va a PrediGol» (A12): the server keeps it ten minutes per time zone. */
  transparency: (preview: Preview) => ({
    queryKey: ["v1", "transparency", preview ?? "user"],
    queryFn: () => v1.transparency({ preview }),
    refetchInterval: 10 * MINUTE,
  }),
  /** The published picks one by one, a page at a time (plan de cierre UX, 1.5): the next page from `meta.next_cursor`. */
  transparencyPickPages: (size: number, preview: Preview) =>
    infiniteQueryOptions({
      queryKey: ["v1", "transparency", "picks", size, preview ?? "user"],
      queryFn: ({ pageParam }) => v1.transparencyPicks({ limit: size, cursor: pageParam, preview }),
      initialPageParam: undefined as string | undefined,
      getNextPageParam: (last) => last.meta.next_cursor ?? undefined,
      refetchInterval: 10 * MINUTE,
    }),
  /** A match's news change when PrediGol Intelligence reads the press again (hours apart; the last hours before kick-off). */
  matchNews: (id: string) => ({
    queryKey: ["v1", "match-news", id],
    queryFn: () => v1.matchNews(id),
    refetchInterval: 5 * MINUTE,
  }),
  /** Home's «Noticias»: the server keeps it two minutes. */
  todayNews: {
    queryKey: ["v1", "today", "news"],
    queryFn: v1.todayNews,
    refetchInterval: 5 * MINUTE,
  },
  liveBoard: { queryKey: ["v1", "live"], queryFn: v1.liveBoard, refetchInterval: 15_000 },
  players: (q: { q?: string | undefined; team_id?: number | undefined }) => ({
    queryKey: ["v1", "players", q.q ?? "", q.team_id ?? 0],
    queryFn: () => v1.players(q),
  }),
  player: (id: string) => ({ queryKey: ["v1", "player", id], queryFn: () => v1.player(id) }),
  /** Referees as people (plan F3). Every decision invalidates the `["v1", "referees"]` prefix. */
  referees: (q: { q?: string | undefined; offset?: number } = {}) => ({
    queryKey: ["v1", "referees", "list", q.q ?? "", q.offset ?? 0],
    queryFn: () => v1.referees(q),
  }),
  refereeQueue: (
    q: { status?: PairStatus; reason?: string | undefined; offset?: number } = {},
  ) => ({
    queryKey: ["v1", "referees", "queue", q.status ?? "open", q.reason ?? "", q.offset ?? 0],
    queryFn: () => v1.refereeQueue(q),
  }),
  referee: (id: string) => ({
    queryKey: ["v1", "referees", "one", id],
    queryFn: () => v1.referee(id),
  }),
  health: { queryKey: ["v1", "health"], queryFn: v1.health, refetchInterval: MINUTE },
  matches: (q: MatchQuery) => ({ queryKey: ["v1", "matches", q], queryFn: () => v1.matches(q) }),
  competitions: { queryKey: ["v1", "competitions"], queryFn: () => v1.competitions() },
  competition: (id: string) => ({
    queryKey: ["v1", "competition", id],
    queryFn: () => v1.competition(id),
  }),
  teams: { queryKey: ["v1", "teams"], queryFn: () => v1.teams() },
  teamSearch: (q: string) => ({
    queryKey: ["v1", "teams", "search", q],
    queryFn: () => v1.teams(undefined, q),
  }),
  team: (id: string) => ({ queryKey: ["v1", "team", id], queryFn: () => v1.team(id) }),
  odds: { queryKey: ["v1", "odds"], queryFn: v1.odds },
  fixtureOdds: (id: string, market?: string) => ({
    queryKey: ["v1", "fixture-odds", id, market ?? "all"],
    queryFn: () => v1.fixtureOdds(id, market),
  }),
  search: (q: string) => ({
    queryKey: ["v1", "search", q],
    queryFn: () => v1.search(q),
    enabled: q.trim().length >= 2,
  }),

  // ── Admin Console ─────────────────────────────────────────────────────────
  admin: { queryKey: ["v1", "admin"], queryFn: v1.admin, refetchInterval: 30_000 },
  /** The storage report is written four times a day: a few minutes is as fresh as it gets. */
  adminStorage: {
    queryKey: ["v1", "admin", "storage"],
    queryFn: v1.adminStorage,
    refetchInterval: 10 * MINUTE,
  },
  overview: { queryKey: ["v1", "overview"], queryFn: v1.overview, refetchInterval: MINUTE },
  quality: { queryKey: ["v1", "quality"], queryFn: v1.quality, refetchInterval: MINUTE },
  coverage: { queryKey: ["v1", "coverage"], queryFn: v1.coverage },
  issues: { queryKey: ["v1", "issues"], queryFn: v1.issues, refetchInterval: MINUTE },
  runs: { queryKey: ["v1", "runs"], queryFn: () => v1.runs(25) },
  jobs: { queryKey: ["v1", "jobs"], queryFn: v1.jobs, refetchInterval: MINUTE },
  match: (id: string) => ({ queryKey: ["v1", "match", id], queryFn: () => v1.match(id) }),
  audit: (id: string) => ({ queryKey: ["v1", "audit", id], queryFn: () => v1.audit(id) }),
  oddsIntelligence: {
    queryKey: ["v1", "odds-intelligence"],
    queryFn: v1.oddsIntelligence,
    staleTime: 10 * MINUTE,
  },
  models: { queryKey: ["v1", "models"], queryFn: v1.models },
  researchV2: { queryKey: ["v1", "research", "v2"], queryFn: v1.researchV2 },
  analyst: { queryKey: ["v1", "analyst"], queryFn: v1.analyst },
  aiStatus: { queryKey: ["v1", "ai", "status"], queryFn: v1.aiStatus, refetchInterval: MINUTE },
  aiRuns: { queryKey: ["v1", "ai", "runs"], queryFn: () => v1.aiRuns(), refetchInterval: MINUTE },
  aiReport: (day: string) => ({
    queryKey: ["v1", "ai", "report", day],
    queryFn: () => v1.aiReport(day || undefined),
  }),
  aiFlags: (source: "qualified" | "evaluation", day: string) => ({
    queryKey: ["v1", "ai", "flags", source, day],
    queryFn: () => v1.aiFlags(source, day || undefined),
  }),
  evolution: { queryKey: ["v1", "evolution"], queryFn: v1.evolution, refetchInterval: MINUTE },
  evolutionDashboard: (day?: string) => ({
    queryKey: ["v1", "evolution", "dashboard", day ?? "today"],
    queryFn: () => v1.evolutionDashboard(day),
    refetchInterval: MINUTE,
  }),
  /** Costs the server a month of predictions (about 4 s): never refreshed by itself, and outside the `evolution` key so a decision does not re-ask. */
  codePromotions: (days?: number) => ({
    queryKey: ["v1", "code-promotions", days ?? "default"],
    queryFn: () => v1.codePromotions(days),
    staleTime: 5 * MINUTE,
  }),
  aiToday: (day?: string) => ({
    queryKey: ["v1", "ai-layer", "today", day ?? "today"],
    queryFn: () => v1.aiToday(day),
    refetchInterval: MINUTE,
  }),
  aiResearch: (day?: string) => ({
    queryKey: ["v1", "ai-layer", "research", day ?? "today"],
    queryFn: () => v1.aiResearch(day),
    refetchInterval: 2 * MINUTE,
  }),
  aiPostmortems: (q: Parameters<typeof v1.aiPostmortems>[0]) => ({
    queryKey: ["v1", "ai-layer", "postmortems", q],
    queryFn: () => v1.aiPostmortems(q),
  }),
  aiDailyReviews: (days = 30) => ({
    queryKey: ["v1", "ai-layer", "daily-reviews", days],
    queryFn: () => v1.aiDailyReviews(days),
    refetchInterval: 10 * MINUTE,
  }),
  aiMatchMemory: (f: MemoryFilters) => ({
    queryKey: ["v1", "ai-layer", "match-memory", f],
    queryFn: () => v1.aiMatchMemory(f),
  }),
  aiDailyReview: (day: string) => ({
    queryKey: ["v1", "ai-layer", "daily-review", day],
    queryFn: () => v1.aiDailyReview(day),
    refetchInterval: 10 * MINUTE,
  }),
  aiSources: (days = 7) => ({
    queryKey: ["v1", "ai-layer", "sources", days],
    queryFn: () => v1.aiSources(days),
  }),
  aiComparison: {
    queryKey: ["v1", "ai-layer", "comparison"],
    queryFn: v1.aiComparison,
    refetchInterval: 10 * MINUTE,
  },
  aiOverview: {
    queryKey: ["v1", "ai-layer", "overview"],
    queryFn: v1.aiOverview,
    refetchInterval: MINUTE,
  },
  aiReviews: (q: Parameters<typeof v1.aiReviews>[0]) => ({
    queryKey: ["v1", "ai-layer", "reviews", q],
    queryFn: () => v1.aiReviews(q),
    refetchInterval: MINUTE,
  }),
  aiReview: (id: number) => ({
    queryKey: ["v1", "ai-layer", "review", id],
    queryFn: () => v1.aiReview(id),
    enabled: id > 0,
  }),
  aiPacket: (fixtureId: string) => ({
    queryKey: ["v1", "ai-layer", "packet", fixtureId],
    queryFn: () => v1.aiPacket(fixtureId),
    enabled: fixtureId !== "",
  }),
  aiEvidence: (q: Parameters<typeof v1.aiEvidence>[0]) => ({
    queryKey: ["v1", "ai-layer", "evidence", q],
    queryFn: () => v1.aiEvidence(q),
    refetchInterval: 2 * MINUTE,
  }),
  aiCosts: {
    queryKey: ["v1", "ai-layer", "costs"],
    queryFn: v1.aiCosts,
    refetchInterval: 5 * MINUTE,
  },
  aiAgents: (days = 7) => ({
    queryKey: ["v1", "ai-layer", "agents", days],
    queryFn: () => v1.aiAgents(days),
    refetchInterval: MINUTE,
  }),
  aiResearchEntities: (days = 7) => ({
    queryKey: ["v1", "ai-layer", "research-entities", days],
    queryFn: () => v1.aiResearchEntities(days),
    refetchInterval: 2 * MINUTE,
  }),
  /** Asked for with a fixture the page has (a match found by the picker); no fixture, no request. */
  aiMatchState: (fixtureId: string) => ({
    queryKey: ["v1", "ai-layer", "match-state", fixtureId],
    queryFn: () => v1.aiMatchState(fixtureId),
    enabled: fixtureId !== "",
    refetchInterval: MINUTE,
  }),
  aiShadow: { queryKey: ["v1", "ai-layer", "shadow"], queryFn: v1.aiShadow, staleTime: 5 * MINUTE },
  aiShadowArms: (days = 30) => ({
    queryKey: ["v1", "ai-layer", "shadow-arms", days],
    queryFn: () => v1.aiShadowArms(days),
    refetchInterval: 5 * MINUTE,
  }),
  aiAttribution: (days = 14) => ({
    queryKey: ["v1", "ai-layer", "attribution", days],
    queryFn: () => v1.aiAttribution(days),
    refetchInterval: 5 * MINUTE,
  }),
  aiContradictions: (days = 7, code?: ContraCode) => ({
    queryKey: ["v1", "ai-layer", "contradictions", days, code ?? "all"],
    queryFn: () => v1.aiContradictions({ days, code, limit: 50 }),
    refetchInterval: 2 * MINUTE,
  }),
  aiAgentRuns: (q: AgentRunsQuery) => ({
    queryKey: ["v1", "ai-layer", "agent-runs", q],
    queryFn: () => v1.aiAgentRuns(q),
    refetchInterval: MINUTE,
  }),
  /** Asked for with a fixture the page has; no fixture, no request. */
  aiMatchShadow: (fixtureId: string, pass?: string) => ({
    queryKey: ["v1", "ai-layer", "match-shadow", fixtureId, pass ?? "newest"],
    queryFn: () => v1.aiMatchShadow(fixtureId, pass),
    enabled: fixtureId !== "",
    refetchInterval: MINUTE,
  }),
  aiMemory: (kind?: string) => ({
    queryKey: ["v1", "ai-layer", "memory", kind ?? "all"],
    queryFn: () => v1.aiMemory(kind),
    refetchInterval: 5 * MINUTE,
  }),
  aiRunRequests: {
    queryKey: ["v1", "ai-layer", "run-requests"],
    queryFn: v1.aiRunRequests,
    refetchInterval: 30_000,
  },
  intelDay: (day?: string) => ({
    queryKey: ["v1", "intel", "day", day ?? "today"],
    queryFn: () => v1.intelDay(day),
    refetchInterval: 2 * MINUTE,
  }),
  intelDecisions: (q: Parameters<typeof v1.intelDecisions>[0]) => ({
    queryKey: ["v1", "intel", "decisions", q],
    queryFn: () => v1.intelDecisions(q),
    refetchInterval: 2 * MINUTE,
  }),
  intelDecision: (id: number) => ({
    queryKey: ["v1", "intel", "decision", id],
    queryFn: () => v1.intelDecision(id),
    enabled: id > 0,
  }),
  intelDossier: (fixtureId: string) => ({
    queryKey: ["v1", "intel", "dossier", fixtureId],
    queryFn: () => v1.intelDossier(fixtureId),
    enabled: fixtureId !== "",
  }),
  intelMatches: (q: Parameters<typeof v1.intelMatches>[0]) => ({
    queryKey: ["v1", "intel", "matches", q],
    queryFn: () => v1.intelMatches(q),
    refetchInterval: 5 * MINUTE,
  }),
  intelFactors: {
    queryKey: ["v1", "intel", "factors"],
    queryFn: v1.intelFactors,
    refetchInterval: 10 * MINUTE,
  },
  intelCalibration: {
    queryKey: ["v1", "intel", "calibration"],
    queryFn: v1.intelCalibration,
    refetchInterval: 10 * MINUTE,
  },
  intelMemory: (q: Parameters<typeof v1.intelMemory>[0]) => ({
    queryKey: ["v1", "intel", "memory", q],
    queryFn: () => v1.intelMemory(q),
  }),
  intelReports: (day?: string) => ({
    queryKey: ["v1", "intel", "reports", day ?? "latest"],
    queryFn: () => v1.intelReports(day),
  }),
  intelMarkets: {
    queryKey: ["v1", "intel", "markets"],
    queryFn: v1.intelMarkets,
    staleTime: 10 * MINUTE,
  },
  intelPriceClock: {
    queryKey: ["v1", "intel", "price-clock"],
    queryFn: v1.intelPriceClock,
    refetchInterval: 5 * MINUTE,
  },
  /** The newest matrix of markets the weekly job stored: it changes once a week, so it is kept 10 minutes. */
  intelMarketMatrix: {
    queryKey: ["v1", "intel", "market-matrix"],
    queryFn: v1.intelMarketMatrix,
    staleTime: 10 * MINUTE,
  },
  /** The families in shadow: the worker writes them hourly and nightly, so a few minutes is as fresh as they get. */
  intelFamilies: (q: Parameters<typeof v1.intelFamilies>[0]) => ({
    queryKey: ["v1", "intel", "families", q],
    queryFn: () => v1.intelFamilies(q),
    refetchInterval: 5 * MINUTE,
  }),
  intelRuns: { queryKey: ["v1", "intel", "runs"], queryFn: v1.intelRuns, refetchInterval: MINUTE },
  intelCosts: {
    queryKey: ["v1", "intel", "costs"],
    queryFn: v1.intelCosts,
    refetchInterval: 5 * MINUTE,
  },
  notifications: {
    queryKey: ["v1", "notifications"],
    queryFn: v1.notifications,
    refetchInterval: MINUTE,
  },
  rankings: (competitionId?: number, pool: RatingPool = "men") => ({
    queryKey: ["v1", "rankings", competitionId ?? "all", pool],
    queryFn: () => v1.rankings(competitionId, pool),
  }),
  picks: { queryKey: ["v1", "picks"], queryFn: v1.picks },
  selectionFunnel: (source: "evaluation" | "qualified") => ({
    queryKey: ["v1", "admin", "selection-funnel", source],
    queryFn: () => v1.selectionFunnel(source),
    refetchInterval: 2 * MINUTE,
  }),
  settlementLatency: {
    queryKey: ["v1", "admin", "settlement-latency"],
    queryFn: () => v1.settlementLatency(7),
    refetchInterval: MINUTE,
  },
  performance: { queryKey: ["v1", "performance"], queryFn: v1.performance },
  competitionProfiles: {
    queryKey: ["v1", "analytics", "competitions"],
    queryFn: v1.competitionProfiles,
    staleTime: 10 * MINUTE,
  },
  teamAnalytics: (id: string) => ({
    queryKey: ["v1", "analytics", "team", id],
    queryFn: () => v1.teamAnalytics(id),
    enabled: id !== "",
  }),
  marketAnalytics: {
    queryKey: ["v1", "analytics", "market"],
    queryFn: v1.marketAnalytics,
    staleTime: 10 * MINUTE,
  },
  experiments: { queryKey: ["v1", "analytics", "experiments"], queryFn: v1.experiments },
  dataCoverage: {
    queryKey: ["v1", "analytics", "coverage"],
    queryFn: v1.dataCoverage,
    staleTime: 10 * MINUTE,
  },
  migration: {
    queryKey: ["v1", "analytics", "migration"],
    queryFn: v1.migration,
    refetchInterval: MINUTE,
  },
  users: { queryKey: ["v1", "admin", "users"], queryFn: v1.users },
  authAudit: (action?: string) => ({
    queryKey: ["v1", "admin", "audit", action ?? "all"],
    queryFn: () => v1.authAudit({ action, limit: 200 }),
    refetchInterval: MINUTE,
  }),
  /** The trail by pages of AUDIT_PAGE events, newest first, as far back as the owner reads (plan UX, B10). */
  authAuditPages: (action?: string) => ({
    queryKey: ["v1", "admin", "audit", "pages", action ?? "all"],
    queryFn: ({ pageParam }: { pageParam: number }) =>
      v1.authAudit({ action, limit: AUDIT_PAGE, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last: Awaited<ReturnType<typeof v1.authAudit>>) => {
      const next = (last.meta.offset ?? 0) + (last.meta.count ?? 0);
      return next < (last.meta.total ?? 0) ? next : undefined;
    },
  }),
  authAuditActions: { queryKey: ["v1", "admin", "audit", "actions"], queryFn: v1.authAuditActions },

  // ── data truth ────────────────────────────────────────────────────────────
  truthLatest: { queryKey: ["v1", "truth", "latest"], queryFn: v1.truthLatest },
  truthRuns: { queryKey: ["v1", "truth", "runs"], queryFn: v1.truthRuns },
  truthV2: { queryKey: ["v1", "truth", "v2"], queryFn: v1.truthV2 },
  truthFindings: (runId: number, q: FindingsQuery) => ({
    queryKey: ["v1", "truth", "findings", runId, q],
    queryFn: () => v1.truthFindings(runId, q),
    enabled: runId > 0,
  }),
  freshness: {
    queryKey: ["v1", "data", "freshness"],
    queryFn: v1.freshness,
    refetchInterval: 2 * MINUTE,
    staleTime: MINUTE,
  },
  datasets: {
    queryKey: ["v1", "data", "datasets"],
    queryFn: v1.datasets,
    refetchInterval: 2 * MINUTE,
    staleTime: MINUTE,
  },
  gate: (hours: number) => ({
    queryKey: ["v1", "data", "gate", hours],
    queryFn: () => v1.gate(hours),
    staleTime: MINUTE,
  }),
  standingsAudit: {
    queryKey: ["v1", "data", "standings"],
    queryFn: v1.standingsAudit,
    refetchInterval: 5 * MINUTE,
  },
  repairs: { queryKey: ["v1", "data", "repairs"], queryFn: v1.repairs },
  validation: {
    queryKey: ["v1", "data", "validation"],
    queryFn: v1.validation,
    staleTime: MINUTE,
  },
  competitionScores: (q: ScoresQuery) => ({
    queryKey: ["v1", "data", "validation", "competitions", q],
    queryFn: () => v1.competitionScores(q),
    staleTime: MINUTE,
  }),
  quarantine: {
    queryKey: ["v1", "data", "validation", "quarantine"],
    queryFn: v1.quarantine,
    staleTime: MINUTE,
  },
  oddsCoverage: (days: number) => ({
    queryKey: ["v1", "data", "odds-coverage", days],
    queryFn: () => v1.oddsCoverage(days),
    staleTime: MINUTE,
  }),
} as const;
