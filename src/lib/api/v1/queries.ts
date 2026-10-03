/** TanStack Query option factories for the live API. */
import { v1, type MatchQuery } from "./client";

const MINUTE = 60_000;

export const live = {
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
  admin: { queryKey: ["v1", "admin"], queryFn: v1.admin, refetchInterval: 30_000 },
  overview: { queryKey: ["v1", "overview"], queryFn: v1.overview, refetchInterval: MINUTE },
  health: { queryKey: ["v1", "health"], queryFn: v1.health, refetchInterval: MINUTE },
  quality: { queryKey: ["v1", "quality"], queryFn: v1.quality, refetchInterval: MINUTE },
  coverage: { queryKey: ["v1", "coverage"], queryFn: v1.coverage },
  issues: { queryKey: ["v1", "issues"], queryFn: v1.issues, refetchInterval: MINUTE },
  runs: { queryKey: ["v1", "runs"], queryFn: () => v1.runs(25) },
  jobs: { queryKey: ["v1", "jobs"], queryFn: v1.jobs, refetchInterval: MINUTE },
  matches: (q: MatchQuery) => ({ queryKey: ["v1", "matches", q], queryFn: () => v1.matches(q) }),
  match: (id: string) => ({ queryKey: ["v1", "match", id], queryFn: () => v1.match(id) }),
  audit: (id: string) => ({ queryKey: ["v1", "audit", id], queryFn: () => v1.audit(id) }),
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
  fixtureOdds: (id: string) => ({
    queryKey: ["v1", "fixture-odds", id],
    queryFn: () => v1.fixtureOdds(id),
  }),
  oddsIntelligence: {
    queryKey: ["v1", "odds-intelligence"],
    queryFn: v1.oddsIntelligence,
    staleTime: 10 * MINUTE,
  },
  models: { queryKey: ["v1", "models"], queryFn: v1.models },
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
  search: (q: string) => ({
    queryKey: ["v1", "search", q],
    queryFn: () => v1.search(q),
    enabled: q.trim().length >= 2,
  }),
} as const;
