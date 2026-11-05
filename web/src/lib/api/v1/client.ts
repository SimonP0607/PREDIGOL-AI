import { reportApiFailure } from "@/lib/observability";
import { API_BASE_URL } from "@/lib/api/mode";
import { markTrouble } from "@/lib/feedback/session";
import type { MatchMarkets, MatchProfile } from "./types_profile";
import type { BuilderQuery, BuiltParlay } from "./types_builder";
import type { SelectionFunnel } from "./types_funnel";
import type { AgentsOverview, MatchState } from "./types_ai_agents";
import type { AttributionOverview } from "./types_ai_attribution";
import type { EntityResearchOverview } from "./types_ai_research";
import type {
  AdminPrivacyRequest,
  ConsentState,
  ConsentsIn,
  ExportDocument,
  LegalDocument,
  LegalDocumentName,
  PrivacyAnswerIn,
  PrivacyRequest,
  PrivacyRequestIn,
  ReauthIn,
} from "./types_customer";
import type {
  NotificationPreferences,
  NotificationPreferencesIn,
  MessageStatus,
  OutboxPreview,
  OutboxSummary,
  UnsubscribeResult,
} from "./types_messaging";
import type { ProductOverview } from "./types_events";
import type {
  AdminCoupon,
  AdminCoupons,
  AdminMembership,
  CouponCreateIn,
  CouponRedeemed,
  MyMembership,
  PaymentIn,
  PaymentRecorded,
} from "./types_membership";
import type {
  AgentRuns,
  AgentRunsQuery,
  ContraCode,
  Contradictions,
  ShadowArms,
  ShadowFile,
} from "./types_ai_shadow";
import type { StorageOverview } from "./types_storage";
import type {
  IntelCalibration,
  IntelCosts,
  IntelDay,
  IntelDecisionDetail,
  IntelDecisionRow,
  IntelDossier,
  IntelFactorsRegistry,
  IntelMarketMatrix,
  IntelMarketRow,
  IntelMemoryRow,
  IntelPicker,
  IntelPriceClock,
  IntelRun,
  IntelState,
} from "./types_intel";
import type { IntelFamilies } from "./types_families";
import type {
  PairStatus,
  RefereeActionResult,
  RefereeDetail,
  RefereeList,
  RefereeMergeBody,
  RefereePairBody,
  RefereeQueue,
  RefereeRenameBody,
  RefereeSplitBody,
} from "./types_referees";

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
  CodePromotions,
  EvolutionOverview,
  HypothesisDecision,
  HypothesisTarget,
  SetSource,
} from "./types_ai";
import type {
  AiComparison,
  AiCosts,
  AiDecision,
  AiEngine,
  DailyReview,
  DailyReviewDay,
  MatchMemory,
  MemoryFilters,
  AiEvidenceRow,
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
import type { MatchCalendar } from "./types_calendar";
import type { MatchForecast } from "./types_forecast";
import type { MatchKnowledge } from "./types_knowledge";
import type { PostMatch } from "./types_postmatch";
import type { MyPicksFilter, PicksSummary } from "./types_mypicks";
import type {
  FeedbackContext,
  FeedbackOverview,
  FeedbackSubject,
  HelpfulIn,
  HelpfulVote,
  SurveyIn,
  SurveyState,
  UpdatesSeen,
} from "./types_feedback";
import type {
  AlertMinutes,
  MatchAlert,
  PushCategories,
  PushCategoriesIn,
  PushDevice,
  PushOverview,
  PushState,
  PushSubscribeIn,
  PushUnsubscribeIn,
} from "./types_push";
import type { MatchReading } from "./types_reading";
import type { ExplainIntent, Explanation, SlipLegBody } from "./types_explain";
import type { PickExplanation } from "./types_explanation";
import type { MatchNews, TodayNews } from "./types_news";
import type { NoPick, Today } from "./types_today";
import type {
  FavoriteOptions,
  FavoritesIn,
  FavoritesView,
  HintKey,
  OnboardingState,
} from "./types_favorites";
import type { Transparency } from "./types_transparency";
import type { AccountSummary } from "./types_account";
import type { PersonalView, Suggestion } from "./types_personal";
import type {
  AdminInbox,
  AdminTicket,
  InboxQuery,
  SupportContact,
  SupportState,
  SupportTicket,
  TicketAnswerIn,
  TicketIn,
} from "./types_support";
import type {
  AuditActionCount,
  ConsentRecord,
  Customer,
  CustomerList,
  CustomerNote,
  CustomerView,
  TicketReview,
} from "./types_customers";
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
  Accepted,
  AccessEvent,
  AccountOptions,
  ActivateIn,
  ActivationInfo,
  AdminAnonymised,
  AdminInviteIn,
  AdminPasswordResult,
  AdminUser,
  AdminUserCreate,
  AuditEvent,
  IdentityIn,
  Me,
  MfaEnrolled,
  MfaEnrollment,
  PreferencesIn,
  ResetIn,
  ResetInfo,
  SelfServiceState,
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
/**
 * Fired when the API says a step of signing in is still owed, that the current consents are (plan UX, A4), or that
 * the membership has ended or is suspended (A8); the auth layer asks /auth/me which.
 */
export const STAGE_EVENT = "predigol:stage";
const STAGE_CODES = new Set([
  "mfa_required",
  "mfa_enrollment_required",
  "password_change_required",
  "consent_required",
  "membership_expired",
  "membership_suspended",
]);

/** How long the last error's request id rides along with a report (plan UX, A14): an older one is not «the» error. */
const LAST_ERROR_MS = 30 * 60 * 1000;
let lastError: { requestId: string; at: number } | null = null;

/**
 * The request id of the last API error this page met in the last half hour, or null (plan UX, A14): «Reportar un
 * problema» attaches it, so the owner finds the server's log line of that error. Never a body, a path or a value.
 */
export function lastApiError(now = Date.now()): string | null {
  return lastError && now - lastError.at <= LAST_ERROR_MS ? lastError.requestId : null;
}

/** For tests: forget the last error. */
export function resetLastApiError(): void {
  lastError = null;
}

/** The filter of Mis picks as query parameters (plan UX, B5): what is not set is left out. */
export function filterParams(
  filter: MyPicksFilter | undefined,
): Record<string, string | number | undefined> {
  const f = filter ?? {};
  return {
    result: f.result ?? undefined,
    market: f.market ?? undefined,
    competition: f.competition ?? undefined,
    origin: f.origin ?? undefined,
    band: f.band ?? undefined,
    since: f.since ?? undefined,
    until: f.until ?? undefined,
    q: f.q?.trim() ? f.q.trim() : undefined,
  };
}

/**
 * The address of a CSV file of the reader's own records (plan UX, B5): a plain download from the page's own origin, with
 * the session cookie, the filter of Mis picks for the picks. A GET: nothing to protect from another site's form.
 */
export function exportUrl(kind: "picks" | "parlays", filter?: MyPicksFilter): string {
  const params = new URLSearchParams();
  if (kind === "picks") {
    for (const [k, v] of Object.entries(filterParams(filter))) {
      if (v !== undefined && v !== "") params.set(k, String(v));
    }
  }
  const query = params.toString();
  return `/api/v1/me/${kind}/export${query ? `?${query}` : ""}`;
}

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
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE",
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
    markTrouble(); // plan UX, B6: no survey after the API was out of reach
    throw new LiveApiError("The API is not reachable.", 0, "unreachable", null);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    markTrouble();
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
    const requestId = err.request_id ?? res.headers.get("x-request-id");
    // the last error a report can point at (plan UX, A14); a sign-in that is simply over is not one
    if (requestId && /^[A-Za-z0-9]{1,32}$/.test(requestId) && res.status !== 401) {
      lastError = { requestId, at: Date.now() };
    }
    // A server error reaches Sentry with its request id, the one in the server's log line (plan UX, A2), and keeps the
    // monthly survey away for the rest of the visit (B6: never after an error).
    if (res.status >= 500) {
      reportApiFailure({ status: res.status, code, requestId, method, path });
      markTrouble();
    }
    throw new LiveApiError(
      err.error?.message ?? `${method} ${path} failed (${res.status})`,
      res.status,
      code,
      requestId,
      (problems as string[] | undefined) ?? [],
      details,
    );
  }
  return parsed as T;
}

const getJson = <T>(path: string, params?: Params) => request<T>("GET", path, { params });
const postJson = <T>(path: string, body: unknown) => request<T>("POST", path, { body });
const putJson = <T>(path: string, body: unknown) => request<T>("PUT", path, { body });
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
  /** Ending another session asks for the password or a code (ASVS 7.5.2); ending this one is signing out. */
  revokeMySession: (id: string, identity: IdentityIn = {}) =>
    postJson<void>(`/auth/me/sessions/${id}/revoke`, identity),
  revokeMyOtherSessions: (identity: IdentityIn) =>
    postJson<{ revoked: number }>("/auth/me/sessions/revoke-others", identity),
  myAccess: (limit = 50) => getJson<AccessEvent[]>("/auth/me/access", { limit }),
  /** The reader's membership: its state now, its periods with their payments and how to renew (plan UX, A8). */
  myMembership: () => getJson<MyMembership>("/me/membership"),
  /** The reader holds a coupon by its code (UX-005). */
  redeemCoupon: (code: string) => postJson<CouponRedeemed>("/me/membership/coupon", { code }),
  /** The profile's eight blocks, folded: one read of the reader's own account (plan UX, B1). */
  myAccount: () => getJson<AccountSummary>("/me/account"),
  // ── what the reader's own use orders and suggests (plan UX, B2) ─────
  myPersonal: () => getJson<PersonalView>("/me/personal"),
  dismissSuggestion: (kind: Suggestion["kind"], id: number) =>
    postJson<PersonalView>("/me/personal/suggestion/dismiss", { kind, id }),
  setMarketOrder: (common: boolean) => putJson<PersonalView>("/me/personal/markets", { common }),
  // getting in without the owner (plan UX, A7): public; a link's token goes in the body, never in a URL
  accountOptions: () => getJson<AccountOptions>("/auth/options"),
  checkInvitation: (token: string) => postJson<ActivationInfo>("/auth/activate/check", { token }),
  activate: (body: ActivateIn) => postJson<Me>("/auth/activate", body),
  renewInvitation: (token: string) => postJson<Accepted>("/auth/activate/renew", { token }),
  forgotPassword: (email: string) => postJson<Accepted>("/auth/password/forgot", { email }),
  checkReset: (token: string) => postJson<ResetInfo>("/auth/password/reset/check", { token }),
  resetPassword: (body: ResetIn) => postJson<void>("/auth/password/reset", body),
  requestUnlock: (email: string) => postJson<Accepted>("/auth/unlock/request", { email }),
  unlock: (token: string) => postJson<void>("/auth/unlock", { token }),
  /** The weekly summary's way out (plan UX, B8): public, the link's token in the body - never in a URL. */
  leaveWeeklySummary: (token: string) =>
    postJson<UnsubscribeResult>("/email/unsubscribe/link", { token }),

  // ── legal texts, consents and the reader's rights (plan UX, A4) ───────────
  /** Public: anyone may read the texts before having an account. */
  legalDocument: (document: LegalDocumentName, lang: "es" | "en") =>
    getJson<LegalDocument>(`/legal/${document}`, { lang }),
  myConsents: (lang: "es" | "en") => getJson<ConsentState>("/me/consents", { lang }),
  decideConsents: (body: ConsentsIn) => postJson<ConsentState>("/me/consents", body),
  /** Everything PrediGol keeps about the reader: the password first (and the code with a second factor). */
  exportMyData: (body: ReauthIn) => postJson<ExportDocument>("/me/export", body),
  myPrivacyRequests: () => getJson<PrivacyRequest[]>("/me/privacy-requests"),
  openPrivacyRequest: (body: PrivacyRequestIn) =>
    postJson<PrivacyRequest>("/me/privacy-requests", body),
  /** Which e-mails the reader receives, by category, and whether their address can receive them (plan UX, A5). */
  myNotificationPreferences: () => getJson<NotificationPreferences>("/me/preferences"),
  updateNotificationPreferences: (body: NotificationPreferencesIn) =>
    patchJson<NotificationPreferences>("/me/preferences", body),

  // ── the reader's favourites, the welcome and the hints (plan UX, A13) ─────
  /** The leagues and teams the reader follows - the suggested ones for Colombia, labelled, while they chose none. */
  myFavorites: () => getJson<FavoritesView>("/me/favorites"),
  /** They become exactly these: 422 too_many_leagues / too_many_teams / unknown_league / unknown_team otherwise. */
  saveFavorites: (body: FavoritesIn) => putJson<FavoritesView>("/me/favorites", body),
  /** Every league PrediGol follows, and the teams of those leagues whose name matches `q` (two letters or more). */
  favoriteOptions: (q = "") => getJson<FavoriteOptions>("/me/favorites/options", { q }),
  myOnboarding: () => getJson<OnboardingState>("/me/onboarding"),
  /** The welcome done or skipped: recorded once, never shown again. */
  completeOnboarding: () => postJson<OnboardingState>("/me/onboarding", {}),
  /** A first-visit hint dismissed: it never comes back. */
  dismissHint: (hint: HintKey) => postJson<OnboardingState>("/me/hints", { hint }),

  // ── what readers think of PrediGol (plan UX, B6) ──────────────────────────
  /** Whether the monthly survey is owed now (once every 30 days from the last answer or skip). */
  mySurvey: () => getJson<SurveyState>("/me/feedback/survey"),
  /** 409 survey_not_due when it was answered or closed in the last 30 days; 404 feedback_off. */
  answerSurvey: (body: SurveyIn) => postJson<{ id: number }>("/me/feedback/survey", body),
  /** The survey closed without an answer: not again for 30 days. */
  skipSurvey: (context: FeedbackContext) => postJson<void>("/me/feedback/survey/skip", { context }),
  myHelpfulVote: (subject: FeedbackSubject, subjectId: number) =>
    getJson<HelpfulVote>("/me/feedback/helpful", { subject, subject_id: subjectId }),
  /** «¿Te sirvió?» answered (the last answer counts): 429 too_many_votes, 404 feedback_off. */
  voteHelpful: (body: HelpfulIn) => putJson<HelpfulVote>("/me/feedback/helpful", body),
  /** The newest entry of Novedades the reader has seen. */
  myUpdatesSeen: () => getJson<UpdatesSeen>("/me/updates/seen"),
  markUpdatesSeen: (id: string) => postJson<UpdatesSeen>("/me/updates/seen", { id }),

  // ── the readers' notices on their devices (plan UX, B7) ───────────────────
  /** Whether notices can be offered (FBI_PUSH and PrediGol's key, P12), the key to subscribe with, devices, categories. */
  myPush: () => getJson<PushState>("/me/push"),
  /** A browser the reader allowed: 422 unknown_push_service or bad_key, 404 push_off. */
  subscribePush: (body: PushSubscribeIn) => postJson<PushDevice>("/me/push/devices", body),
  /** This browser (its address, in the body) or another of the list (its id) stops. */
  unsubscribePush: (body: PushUnsubscribeIn) => postJson<void>("/me/push/devices/stop", body),
  updatePushCategories: (body: PushCategoriesIn) =>
    putJson<PushCategories>("/me/push/categories", body),
  /** «Así se verán tus avisos», now: 409 no_device, 429 too_many_tests (3 a day). */
  sendTestPush: () => postJson<{ id: number }>("/me/push/test", {}),
  /** The bell of a match. */
  myMatchAlert: (fixtureId: number) => getJson<MatchAlert>(`/me/match-alerts/${fixtureId}`),
  /** 422 match_started, too_far (more than 7 days ahead) or too_many_alerts; 404 not_found or push_off. */
  setMatchAlert: (fixtureId: number, minutes: AlertMinutes) =>
    putJson<MatchAlert>(`/me/match-alerts/${fixtureId}`, { minutes_before: minutes }),
  clearMatchAlert: (fixtureId: number) => deleteJson<void>(`/me/match-alerts/${fixtureId}`),

  // ── help and support (plan UX, A14) ───────────────────────────────────────
  /** Public: the WhatsApp number and the reply address, for whoever cannot sign in; nulls until the owner gives them. */
  supportContact: () => getJson<SupportContact>("/support/contact"),
  /** Whether tickets are on, the contact, the categories and the reader's own tickets with their threads. */
  mySupport: () => getJson<SupportState>("/me/support"),
  /** 409 too_many_open (3), 429 too_many_tickets (10 a day), 404 not_available while FBI_SUPPORT is off. */
  openTicket: (body: TicketIn) => postJson<SupportTicket>("/me/support/tickets", body),
  replyTicket: (id: number, text: string) =>
    postJson<SupportTicket>(`/me/support/tickets/${id}/messages`, { text }),
  /** «Ya está resuelto», with how easy it was (1-5) if the reader says. */
  closeTicket: (id: number, effort?: number) =>
    postJson<SupportTicket>(
      `/me/support/tickets/${id}/close`,
      effort === undefined ? {} : { effort },
    ),
  rateTicket: (id: number, effort: number) =>
    postJson<SupportTicket>(`/me/support/tickets/${id}/effort`, { effort }),

  // ── product ───────────────────────────────────────────────────────────────
  home: (q: Preview = {}) => getJson<Envelope<Home>>("/home", q),
  productPicks: (q: PicksQuery & Preview = {}) =>
    getJson<Envelope<PicksBoard>>("/picks", q as Params),
  /** Today's pre-match picks that already kicked off, unfiltered: the page filters them (REVIEW pt 14). */
  startedPicks: (q: Preview = {}) => getJson<Envelope<StartedPick[]>>("/picks/started", q),
  /** «¿Por qué PrediGol eligió este pick?» (plan UX, B3): one published pick in five layers. 404: not a pick a reader sees. */
  pickExplanation: (pickId: number, q: Preview = {}) =>
    getJson<Envelope<PickExplanation>>(`/picks/${pickId}/explanation`, q),
  /** «Explícame» (plan UX, B9): one question of a match or a pick. */
  explain: (entity: "match" | "pick", id: number, intent: ExplainIntent, q: Preview = {}) =>
    getJson<Envelope<Explanation>>("/explain", { entity, id, intent, ...q }),
  /** «¿Por qué baja la probabilidad de mi parlay?» for the legs the slip holds (nothing is stored). */
  explainParlay: (legs: SlipLegBody[]) =>
    postJson<Envelope<Explanation>>("/explain/parlay", { legs }),
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
  /**
   * A page of the user's saved picks: `meta.total` counts them all, `meta.next_cursor` leads on - under the filter of
   * Mis picks when one is given (plan UX, B5).
   */
  myPicks: (
    q: {
      status?: "open" | "settled";
      limit?: number;
      cursor?: string | undefined;
      filter?: MyPicksFilter | undefined;
    } = {},
  ) =>
    getJson<Envelope<UserPick[]>>("/me/picks", {
      status: q.status,
      limit: q.limit ?? 500,
      cursor: q.cursor,
      ...filterParams(q.filter),
    }),
  /** The reader's saved picks under the filter: totals, breakdown and line value, with their sample (plan UX, B5). */
  myPicksSummary: (filter?: MyPicksFilter) =>
    getJson<Envelope<PicksSummary>>("/me/picks/summary", filterParams(filter)),
  savePick: (body: SavePickIn) =>
    postJson<Envelope<{ id: number; snapshot: unknown }>>("/me/picks", body),
  setPickOdds: (id: number, userOdds: string | number | null) =>
    patchJson<void>(`/me/picks/${id}`, { user_odds: userOdds }),
  removePick: (id: number) => deleteJson<void>(`/me/picks/${id}`),
  validateParlay: (legs: LegIn[]) =>
    postJson<Envelope<ParlayValidation>>("/me/parlays/validate", { legs }),
  createParlay: (body: ParlayIn) =>
    postJson<Envelope<{ id: number; combined_odds: string | null }>>("/me/parlays", body),
  /** A page of the user's parlays (`meta.total`, `meta.next_cursor`). */
  myParlays: (q: { limit?: number; cursor?: string | undefined } = {}) =>
    getJson<Envelope<UserParlay[]>>("/me/parlays", { limit: q.limit ?? 200, cursor: q.cursor }),
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
  /**
   * PRONÓSTICO PREDIGOL (plan F5): what PrediGol expects of the match, apart from its value and its picks. Null data
   * with `not_available`: users do not see it yet. `preview: "shadow"` (the Admin Console) adds the fair odds and the
   * decision layer's value and picks beside it.
   */
  matchForecast: (id: number | string, q: Preview = {}) =>
    getJson<Envelope<MatchForecast | null>>(`/matches/${id}/forecast`, q),
  /**
   * CALENDARIO (plan F4): what each team has played and has coming in every competition, and whether the list behind it is
   * whole. Null data with `not_available`: users do not see it yet. `preview: "shadow"` (the Admin Console) shows it either way.
   */
  matchCalendar: (id: number | string, q: Preview = {}) =>
    getJson<Envelope<MatchCalendar | null>>(`/matches/${id}/calendar`, q),
  /**
   * POSTPARTIDO (plan F7): a finished match put together in layers - the result, the statistics of the teams, the events, the
   * players, the tactics and the story of the score, the market from its opening to its close. Facts only. Null data with
   * `not_available`: users do not see it yet (or the match has none, and the section says why). `preview: "shadow"` (the Admin
   * Console) shows it either way, with the row as stored and the chain of rebuilds.
   */
  matchKnowledge: (id: number | string, q: Preview = {}) =>
    getJson<Envelope<MatchKnowledge | null>>(`/matches/${id}/knowledge`, q),
  /**
   * POSTPARTIDO (plan UX, B4): how what the reader saved on the match ended, and how and why each of PrediGol's published picks
   * did - the match's own facts, never what the post-mortem judges. Null data with `not_available`: readers do not see the
   * after-match yet (FBI_KNOWLEDGE_USERS=0). `preview: "shadow"` (the Admin Console) adds the shadow picks.
   */
  matchPostmatch: (id: number | string, q: Preview = {}) =>
    getJson<Envelope<PostMatch | null>>(`/matches/${id}/postmatch`, q),
  /**
   * LECTURA PREDIGOL (plan UX, A9): six sections of facts with their references - summary, context, data, market, risks and
   * the conclusion. Null data with `not_available`: the owner turned it off (FBI_READING_USERS=0).
   */
  matchReading: (id: number | string, q: Preview = {}) =>
    getJson<Envelope<MatchReading | null>>(`/matches/${id}/reading`, q),
  /** HOY (plan UX, A9): the matches around today with the forecast and a line of the reading, and the day's picks state. */
  today: () => getJson<Envelope<Today>>("/today"),
  /** The day's picks state and its reason alone, for the Picks page (the same as /today's no_pick). */
  noPick: () => getJson<Envelope<NoPick>>("/today/no-pick"),
  /** NOTICIAS (plan UX, A10): the match's verified news, confirmed first, rumours and the outdated last. */
  matchNews: (id: string) => getJson<Envelope<MatchNews | null>>(`/matches/${id}/news`),
  /** Home's «Noticias»: the confirmed or probable news of the suggested matches not yet over. */
  todayNews: () => getJson<Envelope<TodayNews | null>>("/today/news"),
  /**
   * CÓMO LE VA A PREDIGOL (plan UX, A12): the published picks and how they went, the days without picks and why, the line
   * value, the forecast's calibration and what is in evaluation - always with its sample. Null data with `not_available`:
   * readers do not see it yet (FBI_TRANSPARENCY). `preview: "shadow"` (the owner) shows it either way.
   */
  transparency: (q: Preview = {}) => getJson<Envelope<Transparency | null>>("/transparency", q),
  liveBoard: () => getJson<Envelope<LiveBoard>>("/live"),
  players: (q: { q?: string | undefined; team_id?: number | undefined; limit?: number } = {}) =>
    getJson<Envelope<PlayerSummary[]>>("/players", {
      q: q.q,
      team_id: q.team_id,
      limit: q.limit ?? 100,
    }),
  player: (id: number | string) => getJson<Envelope<PlayerDetail | null>>(`/players/${id}`),
  /** Referees as people (plan F3): the list, the queue of doubts, one person and the decisions on them. */
  referees: (q: { q?: string | undefined; limit?: number; offset?: number } = {}) =>
    getJson<Envelope<RefereeList>>("/admin/referees", {
      q: q.q,
      limit: q.limit ?? 50,
      offset: q.offset ?? 0,
    }),
  refereeQueue: (
    q: { status?: PairStatus; reason?: string | undefined; limit?: number; offset?: number } = {},
  ) =>
    getJson<Envelope<RefereeQueue>>("/admin/referees/queue", {
      status: q.status ?? "open",
      reason: q.reason,
      limit: q.limit ?? 50,
      offset: q.offset ?? 0,
    }),
  referee: (id: number | string) => getJson<Envelope<RefereeDetail>>(`/admin/referees/${id}`),
  refereeMerge: (id: number, body: RefereeMergeBody) =>
    postJson<Envelope<RefereeActionResult>>(`/admin/referees/${id}/merge`, body),
  refereeUndo: (eventId: number) =>
    postJson<Envelope<RefereeActionResult>>(`/admin/referees/events/${eventId}/undo`, {}),
  refereeSplit: (id: number, body: RefereeSplitBody) =>
    postJson<Envelope<RefereeActionResult>>(`/admin/referees/${id}/split`, body),
  refereeReject: (id: number, body: RefereePairBody) =>
    postJson<Envelope<RefereeActionResult>>(`/admin/referees/${id}/reject`, body),
  refereeReopen: (id: number, body: RefereePairBody) =>
    postJson<Envelope<RefereeActionResult>>(`/admin/referees/${id}/reopen`, body),
  refereeRename: (id: number, body: RefereeRenameBody) =>
    postJson<Envelope<RefereeActionResult>>(`/admin/referees/${id}/rename`, body),
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
  /** The owner's test of error reporting (plan UX, A2): always answers 500, with the request id to look for. */
  monitoringTestError: () => postJson<void>("/admin/monitoring/test-error", {}),
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
  /** The model code against its promotions (plan F12); the server keeps an answer five minutes. */
  codePromotions: (days?: number) =>
    getJson<Envelope<CodePromotions>>("/admin/evolution/code-promotions", { days }),
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
      engine?: AiEngine;
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
  /** The agents (plan IA, phase 1): the registry, the engine of each family, what the state job wrote, the queue and the audit. Reading only. */
  aiAgents: (days = 7) => getJson<Envelope<AgentsOverview>>("/admin/ai/agents", { days }),
  /** Research by entity and topic (plan IA, phase 2): what research v2 kept, found, spent and reused, v1 against v2, and its gate. Reading only. */
  aiResearchEntities: (days = 7) =>
    getJson<Envelope<EntityResearchOverview>>("/admin/ai/research/entities", { days }),
  /** The file of one match: its live state, every state it went through, and the tasks and attempts of the agents on it. */
  aiMatchState: (fixtureId: number | string) =>
    getJson<Envelope<MatchState>>(`/admin/ai/matches/${fixtureId}/state`),
  aiShadow: () => getJson<Envelope<ShadowReportRow[]>>("/admin/ai/shadow"),
  /** The seven arms of the shadow (plan IA phase 3) side by side over the last `days`, the assignments and the "enough data" counts. Reading only. */
  aiShadowArms: (days = 30) => getJson<Envelope<ShadowArms>>("/admin/ai/shadow/arms", { days }),
  /** Plan IA, phase 5: the attribution of the shadow, the coverage of Gate B and the hypotheses by agent and version. */
  aiAttribution: (days = 14) =>
    getJson<Envelope<AttributionOverview>>("/admin/ai/attribution", { days }),
  /** C01-C08 of the shadow: counts by code, what the Council did with what they touch, and the most recent ones. */
  aiContradictions: (q: { days?: number; code?: ContraCode | undefined; limit?: number } = {}) =>
    getJson<Envelope<Contradictions>>("/admin/ai/contradictions", q as Params),
  /** The attempts of the agents on a Bogotá day, with filters, and the day's Opus calls against the shadow's cap. */
  aiAgentRuns: (q: AgentRunsQuery = {}) =>
    getJson<Envelope<AgentRuns>>("/admin/ai/agent-runs", q as Params),
  /** The file of a match for the shadow: assignment, candidates, assessments, contradictions, verdicts side by side, calls. */
  aiMatchShadow: (fixtureId: number | string, pass?: string) =>
    getJson<Envelope<ShadowFile>>(`/admin/ai/matches/${fixtureId}/shadow`, { pass_kind: pass }),
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
  // ── PrediGol Intelligence (Admin Console) ────────────────────────────────
  intelDay: (day?: string) => getJson<Envelope<IntelDay>>("/admin/intelligence/day", { day }),
  intelDecisions: (
    q: {
      day?: string | undefined;
      state?: IntelState | undefined;
      market?: string | undefined;
    } = {},
  ) =>
    getJson<Envelope<{ day: string; items: IntelDecisionRow[] }>>(
      "/admin/intelligence/decisions",
      q as Params,
    ),
  intelDecision: (id: number) =>
    getJson<Envelope<IntelDecisionDetail>>(`/admin/intelligence/decisions/${id}`),
  intelDossier: (fixtureId: number | string) =>
    getJson<Envelope<IntelDossier>>(`/admin/intelligence/matches/${fixtureId}/dossier`),
  /** The dossier's picker: a Bogotá day, or a text (team, competition or match id) within 45 days of it. */
  intelMatches: (
    q: { day?: string | undefined; q?: string | undefined; limit?: number | undefined } = {},
  ) => getJson<Envelope<IntelPicker>>("/admin/intelligence/matches", q as Params),
  /** The registry of context factors as it stands. */
  intelFactors: () => getJson<Envelope<IntelFactorsRegistry>>("/admin/intelligence/factors"),
  intelCalibration: () => getJson<Envelope<IntelCalibration>>("/admin/intelligence/calibration"),
  intelMemory: (
    q: {
      entity_type?: string | undefined;
      q?: string | undefined;
      aspect?: string | undefined;
      limit?: number | undefined;
    } = {},
  ) =>
    getJson<Envelope<{ items: IntelMemoryRow[]; total: number }>>(
      "/admin/intelligence/memory",
      q as Params,
    ),
  intelReports: (day?: string) =>
    getJson<
      Envelope<{
        days: Array<{ day: string; revisions: number; built_at: string }>;
        report: {
          day: string;
          revision: number;
          built_at: string;
          text: string;
          content: Record<string, unknown>;
        } | null;
      }>
    >("/admin/intelligence/reports", { day }),
  intelMarkets: () =>
    getJson<
      Envelope<{
        run: { id: number; started_at: string; status: string } | null;
        by_status: Record<string, number>;
        items: IntelMarketRow[];
      }>
    >("/admin/intelligence/markets"),
  intelPriceClock: () => getJson<Envelope<IntelPriceClock>>("/admin/intelligence/price-clock"),
  intelMarketMatrix: () =>
    getJson<Envelope<IntelMarketMatrix>>("/admin/intelligence/market-matrix"),
  /** The families in shadow (plan F10.17, F11.11): what they decided, how each was graded, what became of it and what they remember. */
  intelFamilies: (
    q: {
      family?: string | undefined;
      state?: string | undefined;
      days?: number | undefined;
      limit?: number | undefined;
    } = {},
  ) => getJson<Envelope<IntelFamilies>>("/admin/intelligence/families", q as Params),
  intelRuns: () =>
    getJson<
      Envelope<{
        items: IntelRun[];
        leakage_audit: Array<{
          day: string;
          rule: string;
          n_checked: number;
          n_violations: number;
          checked_at: string;
        }>;
      }>
    >("/admin/intelligence/runs"),
  intelCosts: () => getJson<Envelope<IntelCosts>>("/admin/intelligence/costs"),
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
  /** The day's selection funnel (REVIEW B1): every stage of the daily set's rule, what stopped where. */
  selectionFunnel: (source: "evaluation" | "qualified") =>
    getJson<Envelope<SelectionFunnel>>("/admin/picks/funnel", { source }),
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
  /** Where the server's disk goes, the copies, the last cleanup and the retention policy (reading only). */
  adminStorage: () => getJson<Envelope<StorageOverview>>("/admin/storage"),
  users: () => getJson<Envelope<AdminUser[]>>("/admin/users"),
  /** The readers' privacy requests (plan UX, A4), open first by their legal deadline. */
  privacyRequests: (status: "open" | "all" = "open") =>
    getJson<AdminPrivacyRequest[]>("/admin/privacy-requests", { status }),
  answerPrivacyRequest: (id: number, body: PrivacyAnswerIn) =>
    postJson<AdminPrivacyRequest>(`/admin/privacy-requests/${id}/answer`, body),
  /** The support inbox (plan UX, A14): tickets and privacy requests, waiting first by priority, with their counts. */
  supportInbox: (q: InboxQuery = {}) =>
    getJson<AdminInbox>("/admin/support", {
      status: q.status ?? "open",
      category: q.category,
      priority: q.priority,
    }),
  answerTicket: (id: number, body: TicketAnswerIn) =>
    postJson<AdminTicket>(`/admin/support/${id}/answer`, body),
  /** The queue of messages to readers (plan UX, A5): sending on or off, today's count, the latest messages. */
  messageQueue: (status?: MessageStatus) =>
    getJson<OutboxSummary>("/admin/messages", status ? { status } : {}),
  messagePreview: (id: number) => getJson<OutboxPreview>(`/admin/messages/${id}/preview`),
  /** Product analytics (plan UX, A6): activation, habit, usage, devices - only with enough readers. */
  productOverview: () => getJson<ProductOverview>("/admin/product"),
  /** The survey with its n, «¿Te sirvió?» per kind and the newest comments (never who wrote them) - plan UX, B6. */
  feedbackOverview: (days = 90) => getJson<FeedbackOverview>("/admin/product/feedback", { days }),
  /** Live devices by browser and a week of notices by category - counts, never who (plan UX, B7). */
  pushOverview: () => getJson<PushOverview>("/admin/product/push"),
  createUser: (body: AdminUserCreate) => postJson<Envelope<AdminUser>>("/admin/users", body),
  /** Invitations (plan UX, A7): whether they can be sent, sending one, sending it again. */
  selfServiceState: () => getJson<SelfServiceState>("/admin/users/self-service"),
  inviteUser: (body: AdminInviteIn) => postJson<Envelope<AdminUser>>("/admin/users/invite", body),
  resendInvitation: (id: number) =>
    postJson<Envelope<AdminUser>>(`/admin/users/${id}/invitation`, {}),
  // the membership (plan UX, A8): the owner records; every answer is the account's membership as the console reads it
  adminMembership: (id: number) => getJson<AdminMembership>(`/admin/users/${id}/membership`),
  // the coupons of the membership (UX-005): the owner creates one when he wants and may disable it
  adminCoupons: () => getJson<AdminCoupons>("/admin/coupons"),
  createCoupon: (body: CouponCreateIn) => postJson<AdminCoupon>("/admin/coupons", body),
  disableCoupon: (id: number) => postJson<AdminCoupon>(`/admin/coupons/${id}/disable`, {}),
  recordPayment: (id: number, body: PaymentIn) =>
    postJson<PaymentRecorded>(`/admin/users/${id}/membership/payments`, body),
  grantCourtesy: (id: number, days: number, reason: string) =>
    postJson<AdminMembership>(`/admin/users/${id}/membership/courtesy`, { days, reason }),
  startTrial: (id: number, days: number) =>
    postJson<AdminMembership>(`/admin/users/${id}/membership/trial`, { days }),
  suspendMembership: (id: number, reason: string) =>
    postJson<AdminMembership>(`/admin/users/${id}/membership/suspend`, { reason }),
  liftMembership: (id: number, reason?: string) =>
    postJson<AdminMembership>(`/admin/users/${id}/membership/lift`, reason ? { reason } : {}),
  renewalIntent: (id: number, willRenew: boolean, reason?: string) =>
    postJson<AdminMembership>(`/admin/users/${id}/membership/renewal`, {
      will_renew: willRenew,
      ...(reason ? { reason } : {}),
    }),
  /** Deleting an account as anonymisation, with its address typed again (plan UX, A7). Cannot be undone. */
  anonymiseUser: (id: number, confirm: string) =>
    postJson<Envelope<AdminAnonymised>>(`/admin/users/${id}/anonymise`, { confirm }),
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
  /** Every kind of event the trail holds, with how many: the audit page's filter (plan UX, B10). */
  authAuditActions: () => getJson<Envelope<AuditActionCount[]>>("/admin/audit/actions"),
  /** One account's open sessions, for the owner: no cookie, only what names them (plan UX, B10). */
  userSessions: (id: number) => getJson<Envelope<SessionInfo[]>>(`/admin/users/${id}/sessions`),

  // ── the customer's card (plan UX, B10) ──────────────────────────────────────
  customers: (q: { view?: CustomerView; q?: string; limit?: number; offset?: number } = {}) =>
    getJson<CustomerList>("/admin/customers", q as Params),
  customer: (id: number) => getJson<Customer>(`/admin/customers/${id}`),
  addCustomerNote: (id: number, note: string) =>
    postJson<Envelope<CustomerNote>>(`/admin/customers/${id}/notes`, { note }),
  /** Reading a reader's consents with their proof is recorded in the trail. */
  customerConsents: (id: number) =>
    getJson<Envelope<ConsentRecord[]>>(`/admin/customers/${id}/consents`),
  /** Reviewing a ticket is recorded in the trail. */
  customerTicket: (id: number, ticketId: number) =>
    getJson<TicketReview>(`/admin/customers/${id}/tickets/${ticketId}`),
  /** The copy of a reader's data, with the owner's password (and code) first; recorded in the trail. */
  exportCustomer: (id: number, body: { password: string; code?: string | null }) =>
    postJson<Record<string, unknown>>(`/admin/customers/${id}/export`, body),

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
