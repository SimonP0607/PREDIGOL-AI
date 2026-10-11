/**
 * The automatic parlay builder (GET /parlays/build, REVIEW PREDIGOL point 15): the parlay PrediGol builds for the
 * user's filters with the rule of its own parlays, each leg with the numbers behind it - or none, and why.
 */
import type { Dec, Iso } from "./types";
import type { CompetitionBadge, ParlayRisk, ProductSource, TeamBadge } from "./types_product";
import type { ItemAi, MarketKey } from "./types_records";

export type BuildReason =
  "no_candidates" | "no_match" | "too_few_legs" | "total_odds_cap" | "no_growth";

export interface BuilderQuery {
  hours: number;
  min_legs: number;
  max_legs: number;
  /** None: every market. */
  market?: MarketKey[] | undefined;
  /** None: every competition. */
  competition_id?: number[] | undefined;
  min_odds?: string | undefined;
  max_odds?: string | undefined;
  max_total_odds?: string | undefined;
}

export interface BuilderLeg {
  pick_id: number;
  fixture_id: number;
  kickoff_at: Iso;
  competition: CompetitionBadge;
  home: TeamBadge;
  away: TeamBadge;
  market_key: string;
  selection: string;
  line: Dec;
  /** The best price available now. */
  odds: Dec;
  bookmaker: string | null;
  price_at: Iso;
  n_bookmakers: number;
  p_model: Dec;
  /** The pessimistic end of the model's interval: what the legs are chosen by. */
  p_low: Dec;
  p_high: Dec | null;
  p_market: Dec;
  fair_odds: Dec;
  edge: Dec;
  /** odds x p_market - 1. */
  price_edge: Dec;
  ev: Dec;
  /** Expected log growth of a 1% stake on this leg alone, at p_low. */
  growth: Dec;
  ai?: ItemAi | null;
}

export interface BuilderFunnel {
  passing: number;
  reviewed: number;
  matching: number;
  combinable: number;
  matches: number;
}

export interface BuilderOption {
  competition: CompetitionBadge;
  selections: number;
}

export interface BuiltParlay {
  status: "ok" | "no_valid_parlay";
  reason: BuildReason | null;
  source: ProductSource;
  rule_version: string;
  parlay_rule: string;
  filters: {
    hours: number;
    min_legs: number;
    max_legs: number;
    markets: string[];
    competition_ids: number[];
    min_odds: Dec | null;
    max_odds: Dec | null;
    max_total_odds: Dec | null;
  };
  legs: BuilderLeg[];
  combined_odds: Dec | null;
  p_all_low: Dec | null;
  p_all_market: Dec | null;
  expected_log_growth: Dec | null;
  risk: ParlayRisk | null;
  correlated_pairs: number;
  funnel: BuilderFunnel;
  competitions: BuilderOption[];
  markets: string[];
  prices_as_of: Iso | null;
  generated_at: Iso;
}
