/**
 * The structured markets of a match by category, each selection with its price IN FORCE - mirrored from
 * backend/src/fbi/api/contracts/market_catalog.py (plan Partidos y Match Center, F4a: M1, M2, M4).
 *
 * Names are stable keys, never words: `key` is `code.period.subject` (e.g. `corners_double_chance.FT.match`) and the
 * selections are the vocabulary of the prices (Home, Draw, Away, 1X, 12, X2, Over, Under, Yes, No, Odd, Even; the
 * provider's own text for HT/FT and highest-scoring-half). The web translates them in `locales/es` and `locales/en`.
 */
import type { Dec, Iso } from "./types";

export type CatalogCategory = "result" | "goals" | "goals_half" | "corners" | "cards" | "shots";

/** Every category the route accepts, in the order the product lists them. */
export const CATALOG_CATEGORIES: readonly CatalogCategory[] = [
  "result",
  "goals",
  "goals_half",
  "corners",
  "cards",
  "shots",
];

/**
 * priced: the provider's newest readable answer before kick-off has prices; withdrawn: its newest answer came back
 * empty, so nothing is in force; unread: answers exist that are not structured yet; never_asked: no pre-match ask.
 */
export type CatalogState = "priced" | "withdrawn" | "unread" | "never_asked";

export interface MarketCatalogBook {
  bookmaker_id: number;
  bookmaker: string;
  /** This bookmaker's price in force for the selection and line. */
  odds: Dec;
  /** In force at least since then: the first ask of the run of identical answers (A -> B -> A: when A came back). */
  captured_at: Iso;
  /** The provider bet type the price came from (307 or 339 for the one corners double chance market). */
  bet_id: number;
}

export interface MarketCatalogSelection {
  selection: string;
  /** 0 when the market has no line; for handicaps, the handicap of this selection. */
  line: Dec;
  best_odds: Dec;
  /** The bookmaker of the best price (ties: by name). */
  bookmaker_id: number;
  bookmaker: string;
  captured_at: Iso;
  /** How many bookmakers have a price in force for this selection and line. */
  bookmakers: number;
  /** Every bookmaker's price in force, best first. */
  books: MarketCatalogBook[];
}

export interface MarketCatalogMarket {
  /** Stable key: code.period.subject. */
  key: string;
  /** What the market prices (goals_over_under, result_1x2, ...); `bet_<id>` for a bet with no code yet. */
  code: string;
  /** FT, 1H, 2H. */
  period: string;
  /** match, home or away. */
  subject: string;
  kind: string;
  has_line: boolean;
  category: CatalogCategory;
  /** Provider bet types read as this one market (307 and 339 are one). */
  bet_ids: number[];
  /** The provider's English name of the bet: a fallback, never shown as a translation. */
  provider_name: string;
  /** 1X2, DC, BTTS, OU or AH: the five settled markets that go to the parlay; null for the others (shown only). */
  market_key: string | null;
  bookmakers: number;
  /** Ordered by line (the home handicap for Asian handicaps) and selection. */
  selections: MarketCatalogSelection[];
}

export interface MarketCatalogCategory {
  key: CatalogCategory;
  markets: number;
  selections: number;
  bookmakers: number;
}

export interface MarketCatalog {
  fixture_id: number;
  kickoff_at: Iso;
  state: CatalogState;
  /** The ask whose answer is in force (null: never asked). */
  checked_at: Iso | null;
  /** A newer answer is not structured yet: the prices are those of the newest one that is. */
  newer_answer_pending: boolean;
  /** A later page of the answer could not be tied to the ask in force and was left out. */
  partial: boolean;
  /** The category asked for; null when none was. */
  category: CatalogCategory | null;
  /** Only the categories with prices in force, in order. */
  categories: MarketCatalogCategory[];
  /** The markets of the category asked for; empty when none was. */
  markets: MarketCatalogMarket[];
}
