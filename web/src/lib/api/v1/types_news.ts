/**
 * The news (plan UX, A10; section 27), as the API returns them. Mirrors fbi.api.contracts.news: per card PrediGol's own
 * summary (Spanish; never the article's words or title), the sources with their standing, the time, the relevance for the
 * match, the status the server decided and the link to the original - and, from A11, the card's own headline in Spanish and
 * English and the summary in English, checked one by one where they were written (null while there are none).
 */
import type { Iso } from "./types";
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

export interface MatchNews {
  fixture_id: number;
  items: NewsItem[];
  counts: Record<NewsStatus, number>;
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
