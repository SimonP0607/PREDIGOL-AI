/**
 * The news (plan UX, A10; section 27), as the API returns them. Mirrors fbi.api.contracts.news: per card PrediGol's own
 * summary (Spanish; never the article's words or title), the sources with their standing, the time, the relevance for the
 * match, the status the server decided and the link to the original - and, from A11, the card's own headline in Spanish and
 * English and the summary in English, checked one by one where they were written (null while there are none).
 */
import type { Dec, Iso } from "./types";
import type { FollowReason } from "./types_today";

export type NewsStatus = "CONFIRMED" | "PROBABLE" | "CONTRADICTORY" | "RUMOR" | "OUTDATED";
export type NewsKind =
  | "injury"
  | "suspension"
  | "doubtful"
  | "lineup"
  | "coach"
  | "news"
  | "transfer"
  | "motivation"
  | "weather"
  | "travel"
  | "schedule"
  | "other";
export type NewsAssertion = "out" | "doubtful" | "available" | "starts" | "info";
export type NewsTier =
  | "official"
  | "competition"
  | "club"
  | "provider"
  | "journalist"
  | "media"
  | "aggregator"
  | "social"
  | "unknown";
export type NewsRelevance = "high" | "medium" | "low";

export interface NewsTeam {
  id: number;
  name: string;
  side: "home" | "away";
}

export interface NewsSource {
  /** The outlet as the search named it (often its address, without www.). */
  name: string;
  tier: NewsTier;
  /** The original page, opened in a new tab; null when the source has no public page. */
  url: string | null;
  published_at: Iso | null;
  /** The source gave only the day: say the day, never an hour. */
  published_day_only: boolean;
}

export interface NewsClaim {
  /** PrediGol's own summary in Spanish; null when it could not be sent - the page words it from kind, player and team. */
  text: string | null;
  lang: "es";
  /** The same summary in English (A11); null when there is none: the English page shows the Spanish, labelled. */
  text_en?: string | null;
  assertion: NewsAssertion;
  sources: NewsSource[];
}

export interface NewsItem {
  id: string;
  kind: NewsKind;
  status: NewsStatus;
  relevance: NewsRelevance;
  team: NewsTeam | null;
  player: string | null;
  /** One; two or more when the sources contradict each other. */
  claims: NewsClaim[];
  /** PrediGol's own headline (A11), at most 80 characters; null for a contradiction and while there is none. */
  headline_es?: string | null;
  headline_en?: string | null;
  published_at: Iso | null;
  published_day_only: boolean;
  seen_at: Iso;
}

/**
 * Whether PrediGol Intelligence searched the web for the match (IA-016): «not searched yet» and «searched, nothing found» are not the same.
 * yes - searched (a search paid for it, or a pass answered by one still fresh); no - no search recorded; unknown - the record was not read.
 */
export interface NewsSearch {
  searched: "yes" | "no" | "unknown";
  /** The newest search; null unless searched is yes. */
  last_searched_at?: Iso | null;
  /** Web searches paid for the match; null when unknown. */
  searches?: number | null;
  /** Pages read for the match, each once; null when unknown (a pass that did not count them). */
  sources_read?: number | null;
}

export interface MatchNews {
  fixture_id: number;
  items: NewsItem[];
  counts: Record<NewsStatus, number>;
  /** Whether and when the web was searched (IA-016); absent from an older API. */
  search?: NewsSearch | null;
}

export interface TodayNewsMatch {
  fixture_id: number;
  kickoff_at: Iso;
  status_group: string;
  home: string;
  away: string;
  competition: string;
  /** Why the match is the reader's (plan UX, B2): a team they follow plays it, or it belongs to a league they follow. */
  followed?: FollowReason | null;
}

export interface TodayNewsItem {
  match: TodayNewsMatch;
  item: NewsItem;
}

export interface TodayNews {
  items: TodayNewsItem[];
  /** The matches are the suggested ones for Colombia (none chosen, or FBI_PERSONALIZATION=0): labelled so. */
  suggested?: boolean;
}

// ── the owner's diagnosis of a match's news (IA-018; SUPER_ADMIN only) ───────────────────────────────────────────────

export type DiagnosisPassKind = "first" | "pre" | "final";
export type DiagnosisCode =
  | "searched"
  | "not_tracked"
  | "no_market"
  | "kicked_off"
  | "day_not_open"
  | "exa_spent"
  | "first_pending"
  | "near_budget"
  | "covered_not_searched"
  | "not_covered";

export interface DiagnosisMatch {
  fixture_id: number;
  kickoff_at: Iso;
  status_group: string;
  home: string;
  away: string;
  competition: string;
  provider_league_id: number | null;
  /** The owner's priority group of the competition: 1 to 4. */
  priority_group: number;
  tracked: boolean;
}

export interface DiagnosisCoverage {
  /** Searched at its first and pre passes whatever the day's caps say (IA-016). */
  covered: boolean;
  switch_on: boolean;
  groups: number[];
}

export interface DiagnosisDay {
  /** The match's day for the AI (America/Bogota). */
  day: string;
  opens_at: Iso;
  opened: boolean;
  /** null: the match is not in the AI's day (its competition is not followed). */
  has_market: boolean | null;
  odds_at?: Iso | null;
}

export interface DiagnosisPass {
  kind: DiagnosisPassKind;
  day: string;
  started_at: Iso;
  finished_at: Iso;
  status: string;
  /** Every web_* count the pass recorded. */
  web: Record<string, number>;
  near_budget: boolean;
}

export interface DiagnosisNextPass {
  kind: DiagnosisPassKind;
  window_from: Iso;
  window_until: Iso;
  /** The final pass: without confirmed line-ups it waits until then. */
  lineups_until?: Iso | null;
  due_now: boolean;
}

export interface DiagnosisSearches {
  searches: number;
  failed: number;
  first_at?: Iso | null;
  last_at?: Iso | null;
  cost_usd: Dec;
  /** null: a pass that searched did not count its pages. */
  sources_read?: number | null;
}

export interface DiagnosisExa {
  allowed: boolean;
  reason: string;
  budget_usd: Dec;
  spent_month_usd: Dec;
  spent_today_usd: Dec;
  daily_cap_usd: Dec;
}

export interface DiagnosisVerdict {
  code: DiagnosisCode;
  at?: Iso | null;
  searches?: number | null;
  pages?: number | null;
  items?: number | null;
  next_pass?: DiagnosisPassKind | null;
  next_at?: Iso | null;
  exa_reason?: string | null;
}

export interface NewsDiagnosis {
  as_of: Iso;
  match: DiagnosisMatch;
  coverage: DiagnosisCoverage;
  day: DiagnosisDay;
  passes: DiagnosisPass[];
  next_pass: DiagnosisNextPass | null;
  searches: DiagnosisSearches;
  /** null when the envelope could not be read. */
  exa: DiagnosisExa | null;
  evidence: Record<NewsStatus, number>;
  evidence_newest_at?: Iso | null;
  verdict: DiagnosisVerdict;
}
