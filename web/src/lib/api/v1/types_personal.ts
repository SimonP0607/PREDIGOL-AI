/**
 * What a reader's own use orders and suggests (plan UX, B2; section 38), as GET /me/personal returns it. Mirrors
 * fbi.api.contracts.personal. Visible rules, never a model: the markets they consult most first in a match's «Mercados»,
 * and one league or team they keep opening and do not follow. Never a pick, a probability, a state or a price.
 */
export type PersonalMarket = "1X2" | "OU" | "BTTS" | "AH" | "DC";

export interface MarketViews {
  market: PersonalMarket;
  /** Times the reader consulted it in the window: opened its bookmakers or all its lines, or chose one of its prices. */
  views: number;
}

export interface MarketOrder {
  /** The reader's markets, most consulted first; the page puts the rest after them in the usual order. Empty: the usual. */
  first: PersonalMarket[];
  /** Why: each of the reader's markets and how many times they consulted it (also while they keep the usual order). */
  views: MarketViews[];
  /** The reader keeps the usual order (and can go back to theirs). */
  common: boolean;
  window_days: number;
  min_views: number;
}

export interface Suggestion {
  kind: "league" | "team";
  id: number;
  name: string;
  /** Different matches of it the reader opened in the window, outside what they follow. */
  matches: number;
  days: number;
}

export interface PersonalView {
  /** FBI_PERSONALIZATION: false gives every reader the common view - the usual order and no suggestion. */
  personalization: boolean;
  /** Whether the reader's use is counted now (the product's analytics on and, where asked, their consent). */
  counted: boolean;
  markets: MarketOrder;
  /** One league or team the reader keeps opening and does not follow: added only when they confirm it. */
  suggestion: Suggestion | null;
}
