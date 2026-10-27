/**
 * «¿Por qué PrediGol eligió este pick?» (plan UX, B3): GET /picks/{id}/explanation. Mirrors fbi.api.contracts.explanation:
 * one pick in five layers - every line a template over these values or a fact of the match's reading, never prose.
 */
import type { Dec, Iso } from "./types";
import type { StatusReason, UserStatus } from "./types_product";
import type { ReadingFact, ReadingNarrative } from "./types_reading";
import type { MatchRef, Stage } from "./types_records";

/** Layer 3: PrediGol's probability against the market's, the price it was published at and the best price now. */
export interface ExplanationMarket {
  /** PrediGol's probability of the selection (calibrated). «Falla aproximadamente n de cada 10 veces» is worded from it. */
  p_model: Dec;
  /** The model's interval (its doubt), when it gave one. */
  p_low: Dec | null;
  p_high: Dec | null;
  /** The market's probability without its margin: now, or when the pick was taken once the match started. */
  p_market: Dec | null;
  /** The day's set's frozen price for a pick of the day; the price the pick was taken at otherwise. */
  published_odds: Dec;
  published_bookmaker: string | null;
  published_at: Iso;
  /** The best price now; null once the match started or without a current price. */
  odds_now: Dec | null;
  bookmaker_now: string | null;
  price_at: Iso | null;
  /** Whether it passes the value rule at the best price now; null once the match started. */
  value_now: boolean | null;
}

/** The pick in PrediGol's set of the day: it passed every step of «Cómo se decide», and this is how it stood then. */
export interface ExplanationDay {
  day: string;
  rank: number;
  stage: Stage;
  selected_at: Iso;
  odds: Dec;
  bookmaker: string | null;
  user_status: UserStatus;
  status_reason: StatusReason;
  context_pending: boolean;
}

/** Only while the AI's review is applied to picks: what it said of this selection. */
export interface ExplanationReview {
  decision: "APPROVE" | "DOWNGRADE" | "REJECT" | "ABSTAIN";
  positives: string[];
  risks: string[];
}

export interface PickExplanation {
  pick_id: number;
  version: string;
  match: MatchRef;
  market_key: string;
  selection: string;
  line: Dec;
  /** Its match kicked off: the numbers it was taken with, never re-priced. */
  started: boolean;
  /** Its state now: at the best price now (as it was taken, once its match started). */
  user_status: UserStatus;
  status_reason: StatusReason;
  context_pending: boolean;
  /** Set when it is one of PrediGol's picks of the day. */
  day: ExplanationDay | null;
  /** False while readers do not see the structured reading: layers 2 and 4 have only the pick's own lines. */
  reading_shown: boolean;
  /** False: PrediGol has not gathered this match's context yet. */
  reading_complete: boolean;
  reading_at: Iso | null;
  /** Layer 2: the reading's context and data facts, each with its reference. */
  context: ReadingFact[];
  /** The validated narrative of that same reading (context, data and risks only): shown instead of the facts. */
  narrative: ReadingNarrative | null;
  market: ExplanationMarket;
  /** Layer 4, besides the pick's own lines: the reading's risks. */
  risks: ReadingFact[];
  review: ExplanationReview | null;
}
