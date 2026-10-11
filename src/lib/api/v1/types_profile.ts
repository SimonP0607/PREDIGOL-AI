/**
 * The two teams before a match, and every price captured for it - mirrored from
 * football-intelligence-v2 src/fbi/api/contracts/profile.py (REVIEW PREDIGOL, points 5 and 10).
 */
import type { Dec, Iso } from "./types";

export type ProfileScopeName = "all" | "competition";
export type ProfileKind = "count" | "average" | "ratio";

export interface ProfileValue {
  /** count: the share of the n matches (0-1); average: the mean; ratio: null. Null: no match carries the data. */
  value: Dec | null;
  /** count: in how many matches it happened; ratio: the numerator (penalties scored). */
  count?: number | null;
  /** ratio: the denominator (penalties taken). */
  total?: number | null;
  /** How many of the matches carry the data this figure is built from. */
  n: number;
}

export interface ProfileMetric {
  key: string;
  kind: ProfileKind;
  home: ProfileValue;
  away: ProfileValue;
}

export interface ProfileScope {
  scope: ProfileScopeName;
  home_matches: number;
  away_matches: number;
  metrics: ProfileMetric[];
}

export interface MatchProfile {
  fixture_id: number;
  window: number;
  scopes: ProfileScope[];
}

export interface BookQuote {
  bookmaker_id: number;
  bookmaker: string;
  odds: Dec;
  captured_at: Iso;
  opening_odds: Dec;
  opening_at: Iso;
  captures: number;
}

export interface SelectionQuotes {
  market_key: string;
  selection: string;
  line: Dec;
  books: BookQuote[];
}

export interface CaptureSummary {
  captured_at: Iso;
  minutes_to_ko: number;
  source: string;
  /** Prices stored by this capture: the number the Cronología shows. */
  quotes: number;
  bookmakers: number;
  by_market: Record<string, number>;
}

export interface MatchMarkets {
  fixture_id: number;
  quotes: number;
  captures: CaptureSummary[];
  selections: SelectionQuotes[];
}
