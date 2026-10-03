import { API_BASE_URL } from "@/lib/api/mode";
import type {
  AnalystReply,
  AnalystStatus,
  CompetitionDetail,
  CompetitionProfile,
  CompetitionSummary,
  CoverageCell,
  CoverageRow,
  Envelope,
  ExperimentSummary,
  FixtureOdds,
  JobHealth,
  MarketAnalytics,
  MatchAudit,
  MatchDetail,
  MatchSummary,
  MigrationProgress,
  ModelsOverview,
  NotificationsOverview,
  OddsIntelligence,
  Overview,
  PerformanceSummary,
  PicksOverview,
  QualityIssue,
  QualityReport,
  Rankings,
  RunSummary,
  SearchHit,
  SystemHealth,
  TeamAnalytics,
  TeamDetail,
  TeamSummary,
  ToolResult,
} from "./types";
import type {
  AdminOverview,
  LiveBoard,
  MatchCenter,
  PlayerDetail,
  PlayerSummary,
} from "./types_center";

/** An error the API itself reported, or a transport failure. */
export class LiveApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
    readonly requestId: string | null,
  ) {
    super(message);
    this.name = "LiveApiError";
  }
}

async function getJson<T>(
  path: string,
  params?: Record<string, string | number | undefined>,
): Promise<T> {
  const url = new URL(`${API_BASE_URL}/api/v1${path}`);
  for (const [k, v] of Object.entries(params ?? {})) {
    if (v !== undefined && v !== "") url.searchParams.set(k, String(v));
  }
  let res: Response;
  try {
    res = await fetch(url, { headers: { accept: "application/json" } });
  } catch {
    throw new LiveApiError(`The API at ${API_BASE_URL} is not reachable.`, 0, "unreachable", null);
  }
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    throw new LiveApiError(`Unexpected response from ${path}.`, res.status, "bad_response", null);
  }
  if (!res.ok) {
    const err = (body ?? {}) as {
      error?: { code?: string; message?: string };
      request_id?: string;
    };
    throw new LiveApiError(
      err.error?.message ?? `GET ${path} failed (${res.status})`,
      res.status,
      err.error?.code ?? "error",
      err.request_id ?? res.headers.get("x-request-id"),
    );
  }
  return body as T;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}/api/v1${path}`, {
      method: "POST",
      headers: { accept: "application/json", "content-type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new LiveApiError(`The API at ${API_BASE_URL} is not reachable.`, 0, "unreachable", null);
  }
  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    throw new LiveApiError(`Unexpected response from ${path}.`, res.status, "bad_response", null);
  }
  if (!res.ok) {
    const err = (parsed ?? {}) as {
      error?: { code?: string; message?: string };
      request_id?: string;
    };
    throw new LiveApiError(
      err.error?.message ?? `POST ${path} failed (${res.status})`,
      res.status,
      err.error?.code ?? "error",
      err.request_id ?? res.headers.get("x-request-id"),
    );
  }
  return parsed as T;
}

export interface MatchQuery {
  date_from?: string;
  date_to?: string;
  status?: string;
  competition_id?: number;
  team_id?: number;
  order?: "asc" | "desc";
  limit?: number;
  offset?: number;
}

export const v1 = {
  health: () => getJson<SystemHealth>("/health"),
  overview: () => getJson<Envelope<Overview>>("/overview"),
  quality: () => getJson<Envelope<QualityReport>>("/health/quality"),
  coverage: () => getJson<Envelope<CoverageRow[]>>("/data-quality/coverage"),
  issues: () => getJson<Envelope<QualityIssue[]>>("/data-quality/issues"),
  runs: (limit = 20) => getJson<Envelope<RunSummary[]>>("/ingestion/runs", { limit }),
  jobs: () => getJson<Envelope<JobHealth[]>>("/ops/jobs"),
  matches: (q: MatchQuery = {}) =>
    getJson<Envelope<MatchSummary[]>>("/matches", q as Record<string, string | number | undefined>),
  match: (id: number | string) => getJson<Envelope<MatchDetail>>(`/matches/${id}`),
  audit: (id: number | string) => getJson<Envelope<MatchAudit>>(`/matches/${id}/audit`),
  competitions: (tracked?: boolean) =>
    getJson<Envelope<CompetitionSummary[]>>("/competitions", {
      tracked: tracked === undefined ? undefined : String(tracked),
      limit: 200,
    }),
  competition: (id: number | string) => getJson<Envelope<CompetitionDetail>>(`/competitions/${id}`),
  teams: (competitionId?: number) =>
    getJson<Envelope<TeamSummary[]>>("/teams", { competition_id: competitionId, limit: 200 }),
  team: (id: number | string) => getJson<Envelope<TeamDetail>>(`/teams/${id}`),
  odds: () => getJson<Envelope<MatchSummary[]>>("/odds"),
  fixtureOdds: (id: number | string, market?: string) =>
    getJson<Envelope<FixtureOdds>>(`/odds/fixtures/${id}`, { market }),
  oddsIntelligence: () => getJson<Envelope<OddsIntelligence>>("/odds/intelligence"),
  analyst: () => getJson<Envelope<AnalystStatus>>("/analyst"),
  analystTool: (name: string, args: Record<string, string | number | undefined>) =>
    getJson<ToolResult>(`/analyst/tools/${encodeURIComponent(name)}`, args),
  ask: (question: string) => postJson<Envelope<AnalystReply | null>>("/analyst/ask", { question }),
  notifications: () => getJson<Envelope<NotificationsOverview>>("/notifications"),
  rankings: (competitionId?: number) =>
    getJson<Envelope<Rankings | null>>("/rankings", { competition_id: competitionId, limit: 200 }),
  models: () => getJson<Envelope<ModelsOverview>>("/models"),
  picks: () => getJson<Envelope<PicksOverview>>("/picks"),
  performance: () => getJson<Envelope<PerformanceSummary>>("/performance"),
  search: (q: string) => getJson<Envelope<SearchHit[]>>("/search", { q, limit: 8 }),
  competitionProfiles: () => getJson<Envelope<CompetitionProfile[]>>("/analytics/competitions"),
  teamAnalytics: (id: number | string) =>
    getJson<Envelope<TeamAnalytics>>(`/analytics/teams/${id}`),
  marketAnalytics: () => getJson<Envelope<MarketAnalytics>>("/analytics/market"),
  experiments: () => getJson<Envelope<ExperimentSummary[]>>("/analytics/experiments"),
  dataCoverage: () => getJson<Envelope<CoverageCell[]>>("/analytics/coverage"),
  migration: () => getJson<Envelope<MigrationProgress>>("/analytics/migration"),
  center: (id: number | string) => getJson<Envelope<MatchCenter | null>>(`/matches/${id}/center`),
  liveBoard: () => getJson<Envelope<LiveBoard>>("/live"),
  players: (q: { q?: string | undefined; team_id?: number | undefined; limit?: number } = {}) =>
    getJson<Envelope<PlayerSummary[]>>("/players", {
      q: q.q,
      team_id: q.team_id,
      limit: q.limit ?? 100,
    }),
  player: (id: number | string) => getJson<Envelope<PlayerDetail | null>>(`/players/${id}`),
  admin: () => getJson<Envelope<AdminOverview>>("/admin/overview"),
};
