/** TanStack Query option factories for the live API. */
import { v1, type MatchQuery } from "./client";
import type { ParlayKind, PicksQuery } from "./types_product";
import type { HistoryPeriod } from "./types_records";
import type { FindingsQuery, ScoresQuery } from "./types_truth";

const MINUTE = 60_000;
type Preview = "shadow" | undefined;

export const live = {
  // ── auth ──────────────────────────────────────────────────────────────────
  me: { queryKey: ["auth", "me"], queryFn: v1.me, staleTime: 5 * MINUTE, retry: false },

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
  parlay: (kind: ParlayKind, preview: Preview) => ({
    queryKey: ["v1", "parlay", kind, preview ?? "qualified"],
    queryFn: () => v1.parlay(kind, { preview }),
    refetchInterval: 2 * MINUTE,
  }),
  bestOdds: (q: { market?: string | undefined; hours?: number | undefined }, preview: Preview) => ({
    queryKey: ["v1", "best-odds", q, preview ?? "qualified"],
    queryFn: () => v1.bestOdds({ ...q, preview }),
    refetchInterval: 2 * MINUTE,
  }),
  daily: (preview: Preview, day?: string) => ({
    queryKey: ["v1", "daily", day ?? "today", preview ?? "qualified"],
    queryFn: () => v1.daily({ day, preview }),
    refetchInterval: 2 * MINUTE,
  }),
  myPicks: {
    queryKey: ["v1", "me", "picks"],
    queryFn: () => v1.myPicks(),
    refetchInterval: 2 * MINUTE,
  },
  myParlays: {
    queryKey: ["v1", "me", "parlays"],
    queryFn: () => v1.myParlays(),
    refetchInterval: 2 * MINUTE,
  },
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
  standings: (id: string) => ({
    queryKey: ["v1", "standings", id],
    queryFn: () => v1.standings(id),
  }),
  center: (id: string) => ({
    queryKey: ["v1", "center", id],
    queryFn: () => v1.center(id),
    refetchInterval: 30_000,
  }),
  liveBoard: { queryKey: ["v1", "live"], queryFn: v1.liveBoard, refetchInterval: 15_000 },
  players: (q: { q?: string | undefined; team_id?: number | undefined }) => ({
    queryKey: ["v1", "players", q.q ?? "", q.team_id ?? 0],
    queryFn: () => v1.players(q),
  }),
  player: (id: string) => ({ queryKey: ["v1", "player", id], queryFn: () => v1.player(id) }),
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
  notifications: {
    queryKey: ["v1", "notifications"],
    queryFn: v1.notifications,
    refetchInterval: MINUTE,
  },
  rankings: (competitionId?: number) => ({
    queryKey: ["v1", "rankings", competitionId ?? "all"],
    queryFn: () => v1.rankings(competitionId),
  }),
  picks: { queryKey: ["v1", "picks"], queryFn: v1.picks },
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

  // ── data truth ────────────────────────────────────────────────────────────
  truthLatest: { queryKey: ["v1", "truth", "latest"], queryFn: v1.truthLatest },
  truthRuns: { queryKey: ["v1", "truth", "runs"], queryFn: v1.truthRuns },
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
