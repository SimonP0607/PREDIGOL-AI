import { API_BASE_URL } from "@/lib/api/mode";
import type { MatchMarkets, MatchProfile } from "./types_profile";
import type { BuilderQuery, BuiltParlay } from "./types_builder";

export interface BestOddsQuery {
  market?: string | undefined;
  hours?: number | undefined;
  picks?: boolean | undefined;
}
import type {
  AiFlags,
  AiReport,
  AiRunKind,
  AiRunRow,
  AiStatus,
  EvolutionOverview,
  HypothesisDecision,
  HypothesisTarget,
  SetSource,
} from "./types_ai";
import type {
  AiComparison,
  AiCosts,
  AiDecision,
  DailyReview,
  DailyReviewDay,
  MatchMemory,
  MemoryFilters,
  AiEvidenceRow,
  AiLearning,
  AiMemoryEvent,
  AiOverview,
  AiPacketView,
  AiResearchRow,
  AiReviewDetail,
  AiReviewRow,
  AiRunQueued,
  AiRunRequest,
  AiSourceRow,
  AiToday,
  EvidenceStatus,
  EvolutionDashboard,
  MatchAnalysis,
  PickPostmortem,
  ShadowReportRow,
} from "./types_ai_layer";
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
  RatingPool,
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
  CompetitionReference,
  CompetitionTable,
  LiveBoard,
  MatchCenter,
  PlayerDetail,
  PlayerSummary,
  ProviderPredictionView,
} from "./types_center";
import type {
  AccessEvent,
  AdminPasswordResult,
  AdminUser,
  AdminUserCreate,
  AuditEvent,
  Me,
  MfaEnrolled,
  MfaEnrollment,
  PreferencesIn,
  SessionInfo,
} from "./types_auth";
import type {
  CompetitionScoreRow,
  DataRepair,
  FindingsQuery,
  DatasetRegister,
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
  StartedPick,
  SettlementLatency,
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
    /** Extra fields of the error: attempts_left, retry_after (seconds). */
    readonly details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "LiveApiError";
  }

  get retryAfter(): number | null {
    const v = this.details["retry_after"];
    return typeof v === "number" ? v : null;
  }

  get attemptsLeft(): number | null {
    const v = this.details["attempts_left"];
    return typeof v === "number" ? v : null;
  }
}

/** Fired when the API says the session is gone; the auth layer sends the reader to sign in. */
export const UNAUTHENTICATED_EVENT = "predigol:unauthenticated";
/** Fired when the API says a step of signing in is still owed; the auth layer asks /auth/me which one. */
export const STAGE_EVENT = "predigol:stage";
const STAGE_CODES = new Set([
  "mfa_required",
  "mfa_enrollment_required",
  "password_change_required",
]);

/** A repeated parameter (`?market=1X2&market=OU`) is an array; an empty one is left out. */
type Params = Record<
  string,
  string | number | boolean | undefined | null | ReadonlyArray<string | number>
>;

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
    if (Array.isArray(v)) {
      for (const item of v as ReadonlyArray<string | number>)
        url.searchParams.append(k, String(item));
    } else if (v !== undefined && v !== null && v !== "") {
      url.searchParams.set(k, String(v));
    }
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
      error?: { code?: string; message?: string; problems?: string[] } & Record<string, unknown>;
      request_id?: string;
    };
    const code = err.error?.code ?? "error";
    if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/auth/")) {
      window.dispatchEvent(new Event(UNAUTHENTICATED_EVENT));
    }
    if (res.status === 403 && STAGE_CODES.has(code) && typeof window !== "undefined") {
      window.dispatchEvent(new Event(STAGE_EVENT));
    }
    const { code: _c, message: _m, problems, ...details } = err.error ?? {};
    throw new LiveApiError(
      err.error?.message ?? `${method} ${path} failed (${res.status})`,
      res.status,
      code,
      err.request_id ?? res.headers.get("x-request-id"),
      (problems as string[] | undefined) ?? [],
      details,
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
  // the steps of signing in
  verifyMfa: (body: { code?: string; recovery_code?: string }) =>
    postJson<Me>("/auth/mfa/verify", body),
  startMfaEnrollment: (password?: string) =>
    postJson<MfaEnrollment>("/auth/mfa/enroll/start", password ? { password } : {}),
  confirmMfaEnrollment: (code: string) =>
    postJson<MfaEnrolled>("/auth/mfa/enroll/confirm", { code }),
  setRequiredPassword: (new_password: string) =>
    postJson<Me>("/auth/password/required", { new_password }),
  // my security
  disableMfa: (password: string, code: string) =>
    postJson<void>("/auth/me/mfa/disable", { password, code }),
  renewRecoveryCodes: (password: string, code: string) =>
    postJson<{ recovery_codes: string[] }>("/auth/me/mfa/recovery-codes", { password, code }),
  mySessions: () => getJson<SessionInfo[]>("/auth/me/sessions"),
  revokeMySession: (id: string) => postJson<void>(`/auth/me/sessions/${id}/revoke`, {}),
  revokeMyOtherSessions: () => postJson<{ revoked: number }>("/auth/me/sessions/revoke-others", {}),
  myAccess: (limit = 50) => getJson<AccessEvent[]>("/auth/me/access", { limit }),

  // ── product ───────────────────────────────────────────────────────────────
  home: (q: Preview = {}) => getJson<Envelope<Home>>("/home", q),
  productPicks: (q: PicksQuery & Preview = {}) =>
    getJson<Envelope<PicksBoard>>("/picks", q as Params),
  /** Today's pre-match picks that already kicked off, unfiltered: the page filters them (REVIEW pt 14). */
  startedPicks: (q: Preview = {}) => getJson<Envelope<StartedPick[]>>("/picks/started", q),
  parlay: (kind: ParlayKind, q: Preview = {}) => getJson<Envelope<Parlay>>(`/parlays/${kind}`, q),
  /** The automatic parlay builder (REVIEW pt 15): nothing is stored - saving it is createParlay. */
  buildParlay: (q: BuilderQuery & Preview) =>
    getJson<Envelope<BuiltParlay>>("/parlays/build", q as unknown as Params),
  /** `picks: false` - prices only (the Cuotas page, REVIEW pt 17): no picks are read. */
  bestOdds: (q: BestOddsQuery & Preview = {}) =>
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
  /** The two teams before the match, each figure with how many matches carry its data (REVIEW pt 5). */
  matchProfile: (id: number | string) =>
    getJson<Envelope<MatchProfile | null>>(`/matches/${id}/profile`),
  /** Every price captured for the match, with the Cronología's numbers (REVIEW pt 10). */
  matchMarkets: (id: number | string) =>
    getJson<Envelope<MatchMarkets | null>>(`/matches/${id}/markets`),
  /** ANÁLISIS PREDIGOL: up to three cards, computed once per match by the worker and read by everyone. */
  matchAnalysis: (id: number | string, q: Preview = {}) =>
    getJson<Envelope<MatchAnalysis | null>>(`/matches/${id}/analysis`, q),
  liveBoard: () => getJson<Envelope<LiveBoard>>("/live"),
  players: (q: { q?: string | undefined; team_id?: number | undefined; limit?: number } = {}) =>
    getJson<Envelope<PlayerSummary[]>>("/players", {
      q: q.q,
      team_id: q.team_id,
      limit: q.limit ?? 100,
    }),
  player: (id: number | string) => getJson<Envelope<PlayerDetail | null>>(`/players/${id}`),
  standings: (competitionId: number | string, season?: number) =>
    getJson<Envelope<CompetitionTable | null>>(`/competitions/${competitionId}/standings`, {
      season,
    }),
  competitionReference: (competitionId: number | string, season?: number) =>
    getJson<Envelope<CompetitionReference | null>>(`/competitions/${competitionId}/reference`, {
      season,
    }),

  // ── Admin Console (SUPER_ADMIN) ───────────────────────────────────────────
  overview: () => getJson<Envelope<Overview>>("/admin/overview"),
  quality: () => getJson<Envelope<QualityReport>>("/admin/health/quality"),
  coverage: () => getJson<Envelope<CoverageRow[]>>("/admin/data-quality/coverage"),
  issues: () => getJson<Envelope<QualityIssue[]>>("/admin/data-quality/issues"),
  runs: (limit = 20) => getJson<Envelope<RunSummary[]>>("/admin/ingestion/runs", { limit }),
  jobs: () => getJson<Envelope<JobHealth[]>>("/admin/ops/jobs"),
  match: (id: number | string) => getJson<Envelope<MatchDetail>>(`/admin/matches/${id}`),
  audit: (id: number | string) => getJson<Envelope<MatchAudit>>(`/admin/matches/${id}/audit`),
  providerPrediction: (id: number | string) =>
    getJson<Envelope<ProviderPredictionView | null>>(`/admin/matches/${id}/provider-prediction`),
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
  evolutionDashboard: (day?: string) =>
    getJson<Envelope<EvolutionDashboard>>("/admin/evolution/dashboard", { day }),
  proposeHypothesis: (body: {
    title: string;
    hypothesis: string;
    rationale: string;
    target?: HypothesisTarget;
  }) => postJson<Envelope<{ id: number }>>("/admin/evolution/hypotheses", body),
  /** RECHAZAR, INVESTIGAR or APROBAR EXPERIMENTO. None of them changes a rule, a model or a pick. */
  decideHypothesis: (id: number, decision: HypothesisDecision | "accept", note?: string) =>
    postJson<Envelope<{ status: string }>>(`/admin/evolution/hypotheses/${id}/decision`, {
      decision,
      note: note || null,
    }),
  /** Only a DONE experiment whose gate passed; the owner types PROMOTE. */
  promoteHypothesis: (id: number, note?: string) =>
    postJson<Envelope<{ status: string }>>(`/admin/evolution/hypotheses/${id}/promote`, {
      confirm: "PROMOTE",
      note: note || null,
    }),

  // ── the AI decision layer (Admin Console) ─────────────────────────────────
  aiOverview: () => getJson<Envelope<AiOverview>>("/admin/ai/overview"),
  aiReviews: (
    q: {
      day?: string | undefined;
      engine?: "combined" | "rules" | "llm";
      decision?: AiDecision | undefined;
      fixture_id?: number | undefined;
      limit?: number;
    } = {},
  ) => getJson<Envelope<AiReviewRow[]>>("/admin/ai/reviews", q as Params),
  aiReview: (id: number) => getJson<Envelope<AiReviewDetail>>(`/admin/ai/reviews/${id}`),
  aiPacket: (fixtureId: number | string) =>
    getJson<Envelope<AiPacketView | null>>(`/admin/ai/packets/${fixtureId}`),
  aiEvidence: (q: { fixture_id?: number | undefined; status?: EvidenceStatus | undefined } = {}) =>
    getJson<Envelope<AiEvidenceRow[]>>("/admin/ai/evidence", q as Params),
  aiCosts: () => getJson<Envelope<AiCosts>>("/admin/ai/costs"),
  aiShadow: () => getJson<Envelope<ShadowReportRow[]>>("/admin/ai/shadow"),
  aiMemory: (kind?: string) => getJson<Envelope<AiMemoryEvent[]>>("/admin/ai/memory", { kind }),
  aiRunRequests: () => getJson<Envelope<AiRunRequest[]>>("/admin/ai/run-requests"),
  aiToday: (day?: string) => getJson<Envelope<AiToday>>("/admin/ai/today", { day }),
  aiResearch: (day?: string) => getJson<Envelope<AiResearchRow[]>>("/admin/ai/research", { day }),
  aiPostmortems: (
    q: {
      day?: string | undefined;
      verdict?: string | undefined;
      classification?: string | undefined;
      fixture_id?: number | undefined;
    } = {},
  ) => getJson<Envelope<PickPostmortem[]>>("/admin/ai/postmortems", q as Params),
  aiLearning: (day?: string) => getJson<Envelope<AiLearning>>("/admin/ai/learning", { day }),
  aiSources: (days = 7) => getJson<Envelope<AiSourceRow[]>>("/admin/ai/sources", { days }),
  aiDailyReviews: (days = 30) =>
    getJson<Envelope<DailyReviewDay[]>>("/admin/ai/daily-reviews", { days }),
  aiMatchMemory: (f: MemoryFilters, limit = 50) =>
    getJson<Envelope<MatchMemory[]>>("/admin/ai/match-memory", { ...f, limit } as Params),
  aiDailyReview: (day: string) =>
    getJson<Envelope<DailyReview | null>>(`/admin/ai/daily-reviews/${day}`),
  aiComparison: () => getJson<Envelope<AiComparison>>("/admin/ai/comparison"),
  requestAiRun: (body: { kind: "analysis" | "learning"; fixture_id?: number | null }) =>
    postJson<Envelope<AiRunQueued>>("/admin/ai/run-requests", body),
  notifications: () => getJson<Envelope<NotificationsOverview>>("/admin/notifications"),
  rankings: (competitionId?: number, pool: RatingPool = "men") =>
    getJson<Envelope<Rankings | null>>("/admin/rankings", {
      competition_id: competitionId,
      pool,
      limit: 200,
    }),
  models: () => getJson<Envelope<ModelsOverview>>("/admin/models"),
  researchV2: () => getJson<Envelope<ResearchOverview>>("/admin/research/v2"),
  picks: () => getJson<Envelope<PicksOverview>>("/admin/picks"),
  settlementLatency: (days = 7) =>
    getJson<Envelope<SettlementLatency>>("/admin/picks/settlement", { days }),
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
  resetUserPassword: (id: number, password?: string) =>
    postJson<Envelope<AdminPasswordResult>>(
      `/admin/users/${id}/password`,
      password ? { password } : {},
    ),
  resetUserMfa: (id: number) => postJson<Envelope<AdminUser>>(`/admin/users/${id}/mfa/reset`, {}),
  unlockUser: (id: number) => postJson<Envelope<AdminUser>>(`/admin/users/${id}/unlock`, {}),
  revokeUserSessions: (id: number) =>
    postJson<Envelope<{ revoked: number }>>(`/admin/users/${id}/sessions/revoke`, {}),
  updateUser: (
    id: number,
    body: { role?: string; status?: "active" | "disabled"; mfa_required?: boolean },
  ) => patchJson<Envelope<AdminUser>>(`/admin/users/${id}`, body),
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
  datasets: () => getJson<Envelope<DatasetRegister>>("/admin/data/datasets"),
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
