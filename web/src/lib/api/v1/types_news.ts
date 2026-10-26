/**
 * The news (plan UX, A10; section 27), as the API returns them. Mirrors fbi.api.contracts.news: per card PrediGol's own
 * summary (Spanish; never the article's words or title), the sources with their standing, the time, the relevance for the
 * match, the status the server decided and the link to the original.
 */
import type { Iso } from "./types";

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
}

export interface TodayNewsItem {
  match: TodayNewsMatch;
  item: NewsItem;
}

export interface TodayNews {
  items: TodayNewsItem[];
}
