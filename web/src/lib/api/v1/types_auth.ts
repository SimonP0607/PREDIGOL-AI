/** Types for /api/v1/auth/* and /api/v1/admin/{users,audit}. Mirrors fbi.api.contracts.auth. */
import type { Display } from "@/lib/display";
import type { Iso } from "./types";
import type { GuideState } from "./types_guides";
import type { MembershipSummary } from "./types_membership";

export type Language = "es" | "en";
export type RoleKey = "SUPER_ADMIN" | "USER";
export type PermissionKey = "app" | "admin" | "admin.users" | "admin.shadow_preview";

/**
 * full: signed in. mfa / enroll / password: a step of signing in is still owed (a code from the authenticator,
 * setting one up, a new password); the session can do nothing else until it is done.
 */
export type Stage = "mfa" | "enroll" | "password" | "full";

/** What a module does with C-16 (plan PM, PM-14-04). */
export type MatrixMode = "off" | "show" | "on";
export type MatrixModule = "odds" | "picks" | "news" | "parlay";
export type MatrixModules = Record<MatrixModule, MatrixMode>;

export interface Me {
  id: number;
  email: string;
  display_name: string;
  role: RoleKey | string;
  permissions: PermissionKey[];
  language: Language;
  /** IANA zone every time on screen is shown in. Stored data stays UTC. */
  timezone: string;
  session_expires_at: Iso;
  /** A session not used for this long ends; every use gives it this long again, never past session_expires_at. */
  session_idle_hours?: number;
  stage: Stage;
  mfa_enabled: boolean;
  /** The role or the owner requires a second factor: it cannot be turned off. */
  mfa_required: boolean;
  must_change_password: boolean;
  recovery_codes_left: number;
  /** The pseudonym this account's errors carry to Sentry (an HMAC the server computes), never the id: plan UX, A2. */
  observability_id?: string | null;
  /**
   * The consents the reader must accept before using the product (plan UX, A4): empty while the gate is off or
   * nothing is owed. GET /auth/me fills it; a 403 consent_required elsewhere means: ask /auth/me again.
   */
  consents_due?: string[];
  /** The membership now (plan UX, A8), filled by GET /auth/me; null or absent for the owner's accounts. */
  membership?: MembershipSummary | null;
  /** «Cómo le va a PrediGol» is open to readers (plan UX, A12; FBI_TRANSPARENCY): link to it only then. */
  transparency?: boolean;
  /** The account still owes its welcome (plan UX, A13; FBI_ONBOARDING): /welcome after the consents. Readers only, once. */
  welcome_due?: boolean;
  /** football (the favourites) and, for a new account, about («Qué es PrediGol»). */
  welcome_steps?: string[];
  /** The first-visit hints the reader dismissed (picks, match, parlay, my_picks): never shown again. */
  hints_seen?: string[];
  /** What the reader has seen of the welcome tour and of the guides of each screen (UX-032). */
  guides?: GuideState[];
  /** FBI_GUIDES: the page shows guides (on unless the owner turned it off). */
  guides_on?: boolean;
  /** The reader's own switch: the guide of each screen on the first visit (on until they turn it off). */
  guides_auto?: boolean;
  /** A reader can write to PrediGol from the page (plan UX, A14; FBI_SUPPORT): «Reportar un problema». */
  support?: boolean;
  /** «Explícame» answers the frequent questions of a match, a pick and the parlay (plan UX, B9; FBI_EXPLAIN): its buttons only then. */
  explain?: boolean;
  /** Legacy: the API still sends it (FBI_ODDS_EXPLORER), but the explorer is the only Cuotas page since PM-13-07 (UX-232) and nothing reads it. */
  odds_explorer?: boolean;
  /** «Estado de los precios» is open to readers (FBI_ODDS_STATUS, off by default): the page links to it only then. */
  odds_status?: boolean;
  /** «Avisos», the reader's inbox, is open (FBI_INBOX, off by default): the page shows its bell only then. */
  inbox?: boolean;
  /** The Noticias section is open to readers (FBI_NEWS_FEED, off by default): the page links to it only then. */
  news_feed?: boolean;
  /** Cuotas opens on the view by match (plan maestro unificado, UX-141; FBI_ODDS_BY_MATCH, off by default). */
  odds_by_match?: boolean;
  /** The bars of the unified plan (UX-152, decisions D-01 and D-02; FBI_NAV_V2, off by default). */
  nav_v2?: boolean;
  /** The readers' global search in the top bar (UX-153; FBI_SEARCH, off by default). */
  search?: boolean;
  /** The pages of a club, a national team and a player, and «Equipos» (UX-154 to UX-157; FBI_PROFILES, off by default). */
  profiles?: boolean;
  /** Noticias as maquetas 08-10 draw it (UX-158 to UX-160; FBI_NEWS_V2, off by default). */
  news_v2?: boolean;
  /** A match's «Intelligence» tab for readers (UX-162 to UX-166; FBI_MATCH_INTELLIGENCE, off by default). */
  match_intelligence?: boolean;
  /** The advanced statistics: profiles, comparisons and the Match Center's statistics (plan EA, C-13; FBI_STATS_V2). */
  stats_v2?: boolean;
  /** The probabilities by market of a match (plan EA, C-14; FBI_MARKET_PROBS). */
  market_probs?: boolean;
  /** Mi parlay accepts every market the catalogue settles (plan EA, EA-501; FBI_PARLAY_MARKETS_V2). */
  parlay_markets_v2?: boolean;
  /** The players' markets of a match (plan EA, C-15; FBI_PLAYER_MARKETS). */
  player_markets?: boolean;
  /** What PrediGol has per competition, datum and market (plan PM, C-16; FBI_AVAILABILITY, off by default): the states
   * «información no disponible» and the owner's console of the matrix only then. */
  availability?: boolean;
  /** The owner's console of the provider's requests by lane, endpoint and competition (plan PM, PM-04-05; FBI_USAGE_CONSOLE). */
  usage_console?: boolean;
  /** The Match Center's shot funnel and its two zones (plan PM, PM-10-01, lámina I01; FBI_MATCH_SHOT_FUNNEL, off by default). */
  match_shot_funnel?: boolean;
  /** The Match Center's balance and strip of the score's state (plan PM, PM-10-02, lámina I01; FBI_MATCH_BALANCE, off by default). */
  match_balance?: boolean;
  /** A competition's page: tables, calendar, leaders and coverage (plan PM, PM-09-04; FBI_COMPETITION_PAGE). */
  competition_page?: boolean;
  /** The season tables computed from the regulation (plan PM, PM-09-01; FBI_COMPETITION_TABLES, off until DOC-008 and DM-14). */
  competition_tables?: boolean;
  /** The world directory of competitions with level and priority (plan PM, PM-09-05; FBI_COMPETITION_DIRECTORY). */
  competition_directory?: boolean;
  /** The player's profile with the new data, the goalkeeper's included (plan PM, PM-08-06; FBI_PLAYER_PROFILE_EXTRAS). */
  player_profile_extras?: boolean;
  /** The calculator «¿Qué pasa si…?» (plan PM, PM-09-03; FBI_WHAT_IF, off until the owner signs DM-14). */
  what_if?: boolean;
  /** One Inicio for everyone, with the «Tus favoritos» strip (plan de correcciones UX, AP-I01, decision D1) (FBI_HOME_UNIFIED, off by default). */
  home_unified?: boolean;
  /** A match's markets as a bookmaker lays them out (plan de correcciones UX, AP-P08, decision D6) (FBI_MARKETS_V3, off by default). */
  markets_v3?: boolean;
  /** «Lo más interesante de hoy» on days without picks (plan de correcciones UX, AP-K04, decision D2) (FBI_DAY_HIGHLIGHTS, off by default). */
  day_highlights?: boolean;
  /** «Mis casas»: the bookmakers the reader plays at, in Perfil, Mercados and Cuotas (plan de correcciones UX, AP-P10, decision D5) (FBI_MY_BOOKS, off by default). */
  my_books?: boolean;
  /** Variable units on picks, parlays, Mis picks and Transparencia (plan de correcciones UX, AP-K07, decision D3) (FBI_STAKES, off by default). */
  stakes?: boolean;
  /** The parlay builder «Por tendencias» (plan de correcciones UX, AP-L02, decision D7) (FBI_TREND_BUILDER, off by default). */
  trend_builder?: boolean;
  /** The data layers of the line-up pitch (plan PM, PM-10-04, lámina I02; FBI_LINEUP_LAYERS, off by default). */
  lineup_layers?: boolean;
  /** The Match Center adapted to the coverage of C-16: tabs and blocks by level (plan PM, PM-14-02; FBI_MATCH_COVERAGE, off). */
  match_coverage?: boolean;
  /** The result forecast also in 100 icons, with «Mito o dato» (plan PM, PM-10-07, lámina I09; FBI_PROB_ICONS, off by default). */
  prob_icons?: boolean;
  /** What Cuotas, Picks, Noticias and Mi parlay do with C-16 (plan PM, PM-14-04; FBI_MATRIX_ODDS, _PICKS, _NEWS, _PARLAY): off (as they
   * always did), show (they read the matrix and only say what it says) or on (it replaces their own check). Absent: all off. */
  matrix_modules?: MatrixModules;
  /** The reader's settings of presentation (decision 8); absent from an API older than BE-039: today's defaults. */
  display?: Display;
}

export interface MfaEnrollment {
  /** Base32 in groups of four, for an app that cannot scan. */
  secret: string;
  otpauth_uri: string;
  /** The same URI as a QR code: an SVG data URI drawn by the server. */
  qr_svg: string;
  issuer: string;
  account: string;
}

export interface MfaEnrolled {
  me: Me;
  /** Shown once. Each works once, in place of a code. */
  recovery_codes: string[];
}

export interface SessionInfo {
  id: string;
  created_at: Iso;
  last_seen_at: Iso;
  expires_at: Iso;
  ip: string | null;
  user_agent: string | null;
  stage: Stage;
  mfa_verified: boolean;
  current: boolean;
}

export interface AccessEvent {
  at: Iso;
  action: string;
  ip: string | null;
  user_agent: string | null;
  reason: string | null;
}

export interface PreferencesIn {
  language?: Language;
  timezone?: string;
  display_name?: string;
  /** Show the guide of each screen on the first visit (UX-032). */
  guides_auto?: boolean;
  /** How PrediGol is shown (decision 8): presentation only. `auto` puts Inicio back on its rule. */
  time_format?: Display["time_format"];
  odds_format?: Display["odds_format"];
  reduce_motion?: boolean;
  home_default?: "mine" | "all" | "auto";
}

/**
 * invited: created by an invitation, not activated yet; deleted: anonymised at the reader's request (plan UX, A7) -
 * its address is masked and nothing about it changes any more.
 */
/** pending: registered by the person, the address not yet confirmed (UX-038): it cannot sign in, has no membership. */
export type AccountStatus = "active" | "disabled" | "invited" | "deleted" | "pending";

export interface AdminUser {
  id: number;
  email: string;
  display_name: string;
  role: RoleKey | string;
  status: AccountStatus;
  language: Language;
  timezone: string;
  created_at: Iso;
  last_login_at: Iso | null;
  active_sessions: number;
  mfa_enabled: boolean;
  mfa_required: boolean;
  must_change_password: boolean;
  /** Set while sign-in is refused after too many failures. */
  locked_until: Iso | null;
  failed_logins: number;
  recovery_codes_left: number;
  /** The membership now (plan UX, A8): read by the list; null for the owner's accounts. */
  membership?: MembershipSummary | null;
}

export interface AdminPasswordResult {
  user: AdminUser;
  /** Only when generated by the server: shown once, never stored. */
  temporary_password: string | null;
}

export interface AdminUserCreate {
  email: string;
  display_name?: string;
  role: RoleKey;
  password: string;
  language: Language;
  timezone: string;
  /** Default true: the account chooses its own password at its first sign-in. */
  must_change_password?: boolean;
  mfa_required?: boolean;
}

export interface AuditEvent {
  id: number;
  at: Iso;
  action: string;
  actor_email: string | null;
  target_email: string | null;
  email: string | null;
  ip: string | null;
  detail: Record<string, unknown>;
}

// ── account and access (plan UX, A7) ──────────────────────────────────────────

/** What the sign-in page may offer: recovery and unlocking by e-mail, only while they work (FBI_SELF_SERVICE). */
export interface AccountOptions {
  self_service: boolean;
  /** A person may create their own account (FBI_SIGNUP on and every lock behind it closed): «Crear cuenta». */
  signup: boolean;
}

/** One required consent of the registration form: its exact sentence, the text it points at and the version in force. */
export interface SignupConsentIn {
  kind: "terms" | "privacy" | "age_18" | "risk_notice" | "marketing_email" | "analytics";
  granted: boolean;
  version: string;
}

/** The registration form (UX-038): the server checks every field and answers 202 whatever the address. */
export interface SignupIn {
  first_name: string;
  last_name: string;
  email: string;
  /** A mobile number; without a country code, Colombian. Kept for the owner's records: never used to send anything. */
  phone: string;
  /** Unique (without regard to case), 3 to 24 characters. */
  nickname: string;
  password: string;
  language: Language;
  timezone: string;
  consents: SignupConsentIn[];
}

/** A confirmation link that works: whose, to fill the page (and for the password manager to save under it). */
export interface VerifyInfo {
  email: string;
  display_name: string;
  language: Language;
}

export interface VerifyIn {
  token: string;
  /** The password chosen when registering: confirming the address also proves it - or, with `replace_password`, the NEW one. */
  password: string;
  /** The person no longer remembers the first password: the link proves the mailbox and this one replaces it (UX-084). */
  replace_password?: boolean;
}

/** An invitation link that works: whose, to fill the page (and for the password manager to save under it). */
export interface ActivationInfo {
  email: string;
  display_name: string;
  language: Language;
  timezone: string;
}

export interface ActivateIn {
  token: string;
  password: string;
  language: Language;
  timezone: string;
}

/** A reset link that works: the address, and whether the account's second factor is asked with the new password. */
export interface ResetInfo {
  email: string;
  mfa: boolean;
}

export interface ResetIn {
  token: string;
  password: string;
  code?: string;
  recovery_code?: string;
}

/** Always the same answer to a request for a link: whether or not the address has an account. */
export interface Accepted {
  status: "accepted";
}

/** Ending another session of one's own account: the password, or a code of the second factor (ASVS 7.5.2). */
export interface IdentityIn {
  password?: string;
  code?: string;
}

export interface AdminInviteIn {
  email: string;
  display_name?: string;
  language: Language;
  timezone: string;
  /** The trial it gets when activated, 7 to 20 days (plan UX, A8); the server's default when left out. */
  trial_days?: number;
}

export interface AdminAnonymised {
  user: AdminUser;
  picks: number;
  parlays: number;
  sessions: number;
  /** Messages still queued for the reader that will not be sent. */
  messages_dropped: number;
  /** Rows of the sign-in trail whose typed address was masked. */
  trail_rows: number;
}

export interface SelfServiceState {
  self_service: boolean;
  /** FBI_EMAIL_SEND: off, invitations wait in the queue. */
  email_sending: boolean;
}
