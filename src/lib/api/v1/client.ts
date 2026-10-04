import { API_BASE_URL } from "@/lib/api/mode";
import type {
  AiFlags,
  AiReport,
  AiRunKind,
  AiRunRow,
  AiStatus,
  EvolutionOverview,
  SetSource,
} from "./types_ai";
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
  MatchView,
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
  CompetitionTable,
  LiveBoard,
  MatchCenter,
  PlayerDetail,
  PlayerSummary,
} from "./types_center";
import type { AdminUser, AdminUserCreate, AuditEvent, Me, PreferencesIn } from "./types_auth";
import type {
  CompetitionScoreRow,
  DataRepair,
  FindingsQuery,
  FreshnessReport,
  GateReport,
  OddsCoverageReport,
  QuarantinedFixture,
  ScoresQuery,
  StandingsAuditRow,
  TruthFinding,
  TruthRun,
  TruthV2Overview,
  EvidenceEntry,
  TruthSummary,
  ValidationSummary,
} from "./types_truth";
import type {
  BestOddsBoard,
  Home,
  Parlay,
  ParlayKind,
  PicksBoard,
  PicksQuery,
} from "./types_product";
import type {
  DailyBoard,
  History,
  HistoryPeriod,
  LegIn,
  ParlayIn,
  ParlayValidation,
  SavePickIn,
  UserParlay,
  UserPick,
} from "./types_records";
import type { ResearchOverview } from "./types_research";

/** An error the API itself reported, or a transport failure. `code` is machine-readable. */
export class LiveApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
    readonly requestId: string | null,
    readonly problems: string[] = [],
  ) {
    super(message);
    this.name = "LiveApiError";
  }
}

/** Fired when the API says the session is gone; the auth layer sends the reader to sign in. */
export const UNAUTHENTICATED_EVENT = "predigol:unauthenticated";

type Params = Record<string, string | number | boolean | undefined | null>;

/**
 * Every request: same origin, the session cookie (HttpOnly - never readable here), and
 * the same-site header the API requires on anything that changes state.
 */
async function request<T>(
  method: "GET" | "POST" | "PATCH" | "DELETE",
  path: string,
  { params, body }: { params?: Params | undefined; body?: unknown } = {},
): Promise<T> {
  // Always the page's own origin in the browser: the session cookie belongs to it, and the
  // web server forwards /api/v1 (vite.config.ts locally, the reverse proxy when deployed).
  const base = typeof window !== "undefined" ? window.location.origin : API_BASE_URL;
  const url = new URL(`${base}/api/v1${path}`);
  for (const [k, v] of Object.entries(params ?? {})) {
    if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, String(v));
  }
  const headers: Record<string, string> = {
    accept: "application/json",
    "x-requested-with": "predigol",
  };
  if (body !== undefined) headers["content-type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(url, {
      method,
      headers,
      credentials: "same-origin",
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });
  } catch {
    throw new LiveApiError("The API is not reachable.", 0, "unreachable", null);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    throw new LiveApiError(`Unexpected response from ${path}.`, res.status, "bad_response", null);
  }
  if (!res.ok) {
    const err = (parsed ?? {}) as {
      error?: { code?: string; message?: string; problems?: string[] };
      request_id?: string;
    };
    const code = err.error?.code ?? "error";
    if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/auth/")) {
      window.dispatchEvent(new Event(UNAUTHENTICATED_EVENT));
    }
    throw new LiveApiError(
      err.error?.message ?? `${method} ${path} failed (${res.status})`,
      res.status,
      code,
      err.request_id ?? res.headers.get("x-request-id"),
      err.error?.problems ?? [],
    );
  }
  return parsed as T;
}

const getJson = <T>(path: string, params?: Params) => request<T>("GET", path, { params });
const postJson = <T>(path: string, body: unknown) => request<T>("POST", path, { body });
const patchJson = <T>(path: string, body: unknown) => request<T>("PATCH", path, { body });
const deleteJson = <T>(path: string) => request<T>("DELETE", path);

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

export interface MatchQuery {
  date_from?: string;
  date_to?: string;
  /** Inclusive instant: with kickoff_before, a day in the reader's own time zone. */
  kickoff_after?: string;
  kickoff_before?: string;
  status?: string;
  competition_id?: number;
  team_id?: number;
  order?: "asc" | "desc";
  limit?: number;
  offset?: number;
}

/** `preview: "shadow"` is the Admin Console's labelled preview; the API refuses it to a USER. */
type Preview = { preview?: "shadow" | undefined };

export const v1 = {
  // ── auth ──────────────────────────────────────────────────────────────────
  login: (email: string, password: string) => postJson<Me>("/auth/login", { email, password }),
  logout: () => postJson<void>("/auth/logout", {}),
  me: () => getJson<Me>("/auth/me"),
  updatePreferences: (prefs: PreferencesIn) => patchJson<Me>("/auth/me/preferences", prefs),
  changePassword: (current_password: string, new_password: string) =>
    postJson<void>("/auth/me/password", { current_password, new_password }),

  // ── product ───────────────────────────────────────────────────────────────
  home: (q: Preview = {}) => getJson<Envelope<Home>>("/home", q),
  productPicks: (q: PicksQuery & Preview = {}) =>
    getJson<Envelope<PicksBoard>>("/picks", q as Params),
  parlay: (kind: ParlayKind, q: Preview = {}) => getJson<Envelope<Parlay>>(`/parlays/${kind}`, q),
  bestOdds: (q: { market?: string | undefined; hours?: number | undefined } & Preview = {}) =>
    getJson<Envelope<BestOddsBoard>>("/odds/best", q as Params),

  // ── records: the day as persisted, and the user's own ──────────────────────
  daily: (q: { day?: string | undefined } & Preview = {}) =>
    getJson<Envelope<DailyBoard>>("/daily", q as Params),
  myPicks: (status?: "open" | "settled") =>
    getJson<Envelope<UserPick[]>>("/me/picks", { status, limit: 500 }),
  savePick: (body: SavePickIn) =>
    postJson<Envelope<{ id: number; snapshot: unknown }>>("/me/picks", body),
  setPickOdds: (id: number, userOdds: string | number | null) =>
    patchJson<void>(`/me/picks/${id}`, { user_odds: userOdds }),
  removePick: (id: number) => deleteJson<void>(`/me/picks/${id}`),
  validateParlay: (legs: LegIn[]) =>
    postJson<Envelope<ParlayValidation>>("/me/parlays/validate", { legs }),
  createParlay: (body: ParlayIn) =>
    postJson<Envelope<{ id: number; combined_odds: string | null }>>("/me/parlays", body),
  myParlays: () => getJson<Envelope<UserParlay[]>>("/me/parlays", { limit: 200 }),
  removeParlay: (id: number) => deleteJson<void>(`/me/parlays/${id}`),
  history: (period: HistoryPeriod, q: Preview = {}) =>
    getJson<Envelope<History>>("/me/history", { period, ...q }),

  // ── football (any signed-in account) ───────────────────────────────────────
  health: () => getJson<SystemHealth>("/health"),
  matches: (q: MatchQuery = {}) => getJson<Envelope<MatchSummary[]>>("/matches", q as Params),
  matchView: (id: number | string) => getJson<Envelope<MatchView>>(`/matches/${id}`),
  competitions: (tracked?: boolean) =>
    getJson<Envelope<CompetitionSummary[]>>("/competitions", {
      tracked: tracked === undefined ? undefined : String(tracked),
      limit: 200,
    }),
  competition: (id: number | string) => getJson<Envelope<CompetitionDetail>>(`/competitions/${id}`),
  teams: (competitionId?: number, q?: string) =>
    getJson<Envelope<TeamSummary[]>>("/teams", { competition_id: competitionId, q, limit: 200 }),
  team: (id: number | string) => getJson<Envelope<TeamDetail>>(`/teams/${id}`),
  odds: () => getJson<Envelope<MatchSummary[]>>("/odds"),
  fixtureOdds: (id: number | string, market?: string) =>
    getJson<Envelope<FixtureOdds>>(`/odds/fixtures/${id}`, { market }),
  search: (q: string) => getJson<Envelope<SearchHit[]>>("/search", { q, limit: 8 }),
  center: (id: number | string) => getJson<Envelope<MatchCenter | null>>(`/matches/${id}/center`),
  liveBoard: () => getJson<Envelope<LiveBoard>>("/live"),
  players: (q: { q?: string | undefined; team_id?: number | undefined; limit?: number } = {}) =>
    getJson<Envelope<PlayerSummary[]>>("/players", {
      q: q.q,
      team_id: q.team_id,
      limit: q.limit ?? 100,
    }),
  player: (id: number | string) => getJson<Envelope<PlayerDetail | null>>(`/players/${id}`),
  standings: (competitionId: number | string) =>
    getJson<Envelope<CompetitionTable | null>>(`/competitions/${competitionId}/standings`),

  // ── Admin Console (SUPER_ADMIN) ───────────────────────────────────────────
  overview: () => getJson<Envelope<Overview>>("/admin/overview"),
  quality: () => getJson<Envelope<QualityReport>>("/admin/health/quality"),
  coverage: () => getJson<Envelope<CoverageRow[]>>("/admin/data-quality/coverage"),
  issues: () => getJson<Envelope<QualityIssue[]>>("/admin/data-quality/issues"),
  runs: (limit = 20) => getJson<Envelope<RunSummary[]>>("/admin/ingestion/runs", { limit }),
  jobs: () => getJson<Envelope<JobHealth[]>>("/admin/ops/jobs"),
  match: (id: number | string) => getJson<Envelope<MatchDetail>>(`/admin/matches/${id}`),
  audit: (id: number | string) => getJson<Envelope<MatchAudit>>(`/admin/matches/${id}/audit`),
  oddsIntelligence: () => getJson<Envelope<OddsIntelligence>>("/admin/odds/intelligence"),
  analyst: () => getJson<Envelope<AnalystStatus>>("/admin/analyst"),
  analystTool: (name: string, args: Record<string, string | number | undefined>) =>
    getJson<ToolResult>(`/admin/analyst/tools/${encodeURIComponent(name)}`, args),
  ask: (question: string) =>
    postJson<Envelope<AnalystReply | null>>("/admin/analyst/ask", { question }),
  aiStatus: () => getJson<Envelope<AiStatus>>("/admin/ai/status"),
  aiRuns: (kind?: AiRunKind) =>
    getJson<Envelope<AiRunRow[]>>("/admin/ai/runs", { kind, limit: 50 }),
  aiReport: (day?: string) => getJson<Envelope<AiReport | null>>("/admin/ai/report", { day }),
  aiFlags: (source: SetSource, day?: string) =>
    getJson<Envelope<AiFlags>>("/admin/ai/flags", { day, source }),
  aiReportRun: (day?: string) =>
    postJson<Envelope<AiReport | null>>("/admin/ai/report/run", day ? { day } : {}),
  aiReviewRun: (source: SetSource, day?: string) =>
    postJson<Envelope<AiFlags>>("/admin/ai/review/run", day ? { day, source } : { source }),
  evolution: () => getJson<Envelope<EvolutionOverview>>("/admin/evolution"),
  proposeHypothesis: (body: { title: string; hypothesis: string; rationale: string }) =>
    postJson<Envelope<{ id: number }>>("/admin/evolution/hypotheses", body),
  decideHypothesis: (id: number, decision: "accept" | "reject", note?: string) =>
    postJson<Envelope<{ status: string }>>(`/admin/evolution/hypotheses/${id}/decision`, {
      decision,
      note: note || null,
    }),
  notifications: () => getJson<Envelope<NotificationsOverview>>("/admin/notifications"),
  rankings: (competitionId?: number) =>
    getJson<Envelope<Rankings | null>>("/admin/rankings", {
      competition_id: competitionId,
      limit: 200,
    }),
  models: () => getJson<Envelope<ModelsOverview>>("/admin/models"),
  researchV2: () => getJson<Envelope<ResearchOverview>>("/admin/research/v2"),
  picks: () => getJson<Envelope<PicksOverview>>("/admin/picks"),
  performance: () => getJson<Envelope<PerformanceSummary>>("/admin/performance"),
  competitionProfiles: () =>
    getJson<Envelope<CompetitionProfile[]>>("/admin/analytics/competitions"),
  teamAnalytics: (id: number | string) =>
    getJson<Envelope<TeamAnalytics>>(`/admin/analytics/teams/${id}`),
  marketAnalytics: () => getJson<Envelope<MarketAnalytics>>("/admin/analytics/market"),
  experiments: () => getJson<Envelope<ExperimentSummary[]>>("/admin/analytics/experiments"),
  dataCoverage: () => getJson<Envelope<CoverageCell[]>>("/admin/analytics/coverage"),
  migration: () => getJson<Envelope<MigrationProgress>>("/admin/analytics/migration"),
  admin: () => getJson<Envelope<AdminOverview>>("/admin/system"),
  users: () => getJson<Envelope<AdminUser[]>>("/admin/users"),
  createUser: (body: AdminUserCreate) => postJson<Envelope<AdminUser>>("/admin/users", body),
  updateUser: (id: number, body: { role?: string; status?: "active" | "disabled" }) =>
    patchJson<Envelope<AdminUser>>(`/admin/users/${id}`, body),
  authAudit: (q: { action?: string | undefined; limit?: number; offset?: number } = {}) =>
    getJson<Envelope<AuditEvent[]>>("/admin/audit", q as Params),

  // ── data truth ────────────────────────────────────────────────────────────
  truthLatest: () => getJson<Envelope<TruthSummary | null>>("/admin/truth/latest"),
  truthRun: (id: number) => getJson<Envelope<TruthSummary | null>>(`/admin/truth/runs/${id}`),
  truthRuns: () => getJson<Envelope<TruthRun[]>>("/admin/truth/runs", { limit: 30 }),
  truthV2: () => getJson<Envelope<TruthV2Overview>>("/admin/truth/v2", { limit: 300 }),
  decideEvidence: (
    code: string,
    status: "OPEN" | "FIXED" | "ACCEPTED" | "MONITOR",
    note?: string,
  ) => postJson<Envelope<EvidenceEntry | null>>(`/admin/truth/v2/ledger/${code}`, { status, note }),
  truthFindings: (runId: number, q: FindingsQuery = {}) =>
    getJson<Envelope<TruthFinding[]>>(`/admin/truth/runs/${runId}/findings`, q as Params),
  freshness: () => getJson<Envelope<FreshnessReport>>("/admin/data/freshness"),
  gate: (hours = 72) => getJson<Envelope<GateReport>>("/admin/data/gate", { horizon_hours: hours }),
  standingsAudit: () => getJson<Envelope<StandingsAuditRow[]>>("/admin/data/standings"),
  repairs: () => getJson<Envelope<DataRepair[]>>("/admin/data/repairs", { limit: 200 }),
  validation: () => getJson<Envelope<ValidationSummary>>("/admin/data/validation"),
  competitionScores: (q: ScoresQuery = {}) =>
    getJson<Envelope<CompetitionScoreRow[]>>("/admin/data/validation/competitions", q as Params),
  quarantine: () =>
    getJson<Envelope<QuarantinedFixture[]>>("/admin/data/validation/quarantine", { limit: 200 }),
  oddsCoverage: (days = 14) =>
    getJson<Envelope<OddsCoverageReport>>("/admin/data/odds-coverage", { days }),
};
