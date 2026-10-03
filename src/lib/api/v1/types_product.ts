/**
 * Types for the product endpoints: /home, /picks, /parlays/{kind}, /odds/best.
 * Mirrors fbi.api.contracts.product. Where a block is empty its `reason` is a CODE
 * (no_qualified_picks, no_value_now, ...) that the UI translates.
 */
import type { Dec, Iso, Section } from "./types";
import type { LiveMatch } from "./types_center";

export type ProductSource = "qualified" | "shadow_preview";
export type PriceFreshness = "fresh" | "aging" | "stale" | "none";

export interface TeamBadge {
  id: number;
  name: string;
  logo_url: string | null;
}

export interface CompetitionBadge {
  id: number;
  name: string;
  country: string | null;
  logo_url: string | null;
  flag_url: string | null;
}

export interface PickCard {
  pick_id: number;
  fixture_id: number;
  kickoff_at: Iso;
  competition: CompetitionBadge;
  home: TeamBadge;
  away: TeamBadge;
  market_key: string;
  selection: string;
  line: Dec;
  status: "shadow" | "qualified" | "published";
  model: string;
  /** Best price available now (latest de-vigged consensus). */
  best_odds: Dec | null;
  bookmaker: string | null;
  price_at: Iso | null;
  /** Model probability, conditional on the bet being settled. */
  p_model: Dec;
  /** De-vigged market consensus probability. */
  p_market: Dec | null;
  fair_odds: Dec | null;
  edge: Dec | null;
  /** Expected value per unit at best_odds. */
  ev: Dec | null;
  freshness: PriceFreshness;
  value_now: boolean;
  /** The gate it fails, as a code, when value_now is false. */
  value_reason: string | null;
}

export interface PicksBoard {
  source: ProductSource;
  top: PickCard[];
  picks: PickCard[];
  competitions: CompetitionBadge[];
  markets: string[];
  window_hours: number;
  reason: string | null;
}

export interface ParlayLeg {
  pick_id: number;
  fixture_id: number;
  kickoff_at: Iso;
  competition: CompetitionBadge;
  home: TeamBadge;
  away: TeamBadge;
  market_key: string;
  selection: string;
  line: Dec;
  odds: Dec;
  bookmaker: string | null;
  price_at: Iso;
  p_model: Dec;
  p_market: Dec;
  p_win: Dec;
  edge: Dec;
  ev: Dec;
}

export type ParlayKind = "daily" | "multiday";
export type ParlayRisk = "moderate" | "high" | "very_high";

export interface Parlay {
  kind: ParlayKind;
  status: "ok" | "no_valid_parlay";
  source: ProductSource;
  legs: ParlayLeg[];
  required_legs: number;
  max_legs: number;
  /** Selections that passed the value gate in the window. */
  eligible_legs: number;
  window_from: Iso;
  window_to: Iso;
  combined_odds: Dec | null;
  /** Product of the legs' win probabilities; null when independence does not hold. */
  probability_all_win: Dec | null;
  /** Per unit: product of (1 + leg EV) minus one. */
  expected_value: Dec | null;
  risk: ParlayRisk | null;
  independence: "distinct_fixtures_and_teams" | "not_independent" | null;
  /** The oldest price among the legs. */
  prices_as_of: Iso | null;
  /** Selections left out, by the rule they failed (codes). */
  rejections: Record<string, number>;
  generated_at: Iso;
}

export interface BestPrice {
  selection: string;
  best_odds: Dec;
  bookmaker: string | null;
  p_fair: Dec;
  fair_odds: Dec;
  /** best_odds * p_fair - 1. */
  price_edge: Dec;
  /** More than 25% above fair: very likely one book's stale or mistaken quote. Never highlighted. */
  outlier?: boolean;
  n_bookmakers: number;
  as_of: Iso;
}

export interface BestMarket {
  market_key: string;
  line: Dec;
  selections: BestPrice[];
}

export interface BestOddsFixture {
  fixture_id: number;
  kickoff_at: Iso;
  competition: CompetitionBadge;
  home: TeamBadge;
  away: TeamBadge;
  markets: BestMarket[];
  as_of: Iso;
}

export interface BestHighlight {
  fixture_id: number;
  kickoff_at: Iso;
  competition: CompetitionBadge;
  home: TeamBadge;
  away: TeamBadge;
  market_key: string;
  line: Dec;
  price: BestPrice;
}

export interface BestOddsBoard {
  window_hours: number;
  markets: string[];
  fixtures: BestOddsFixture[];
  highlights: BestHighlight[];
  value: PickCard[];
  source: ProductSource;
}

export interface UpcomingMatch {
  fixture_id: number;
  kickoff_at: Iso;
  competition: CompetitionBadge;
  home: TeamBadge;
  away: TeamBadge;
  bookmakers: number;
}

export interface Home {
  source: ProductSource;
  data_freshness: { odds_at: Iso | null; live_at: Iso | null };
  top_picks: Section<PickCard[]>;
  daily_parlay: Parlay;
  multiday_parlay: Parlay;
  live: Section<LiveMatch[]>;
  best_prices: Section<BestHighlight[]>;
  upcoming: Section<UpcomingMatch[]>;
}

export interface PicksQuery {
  competition_id?: number | undefined;
  market?: string | undefined;
  min_odds?: number | undefined;
  max_odds?: number | undefined;
  hours?: number | undefined;
}
