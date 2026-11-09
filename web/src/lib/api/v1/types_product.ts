/**
 * Types for the product endpoints: /home, /picks, /parlays/{kind}, /odds/best.
 * Mirrors fbi.api.contracts.product. Where a block is empty its `reason` is a CODE
 * (no_qualified_picks, no_value_now, ...) that the UI translates.
 */
import type { Dec, Iso, MatchPhase, Section } from "./types";
import type { LiveMatch } from "./types_center";

export type ProductSource = "qualified" | "shadow_preview";
export type PriceFreshness = "fresh" | "aging" | "stale" | "none";

/**
 * The visible state of a pick (plan UX, B3; fbi/picks/user_status.py, the one table): RECOMMENDED, CAUTION (the applied AI
 * review downgrades it), NOT_RECOMMENDED (no value at its price, or the applied review rejects it) or EVALUATION (a shadow
 * pick). A reader is shown RECOMMENDED picks only (UX-002, «solo verde»); the others reach the owner's preview alone.
 */
export type UserStatus = "RECOMMENDED" | "CAUTION" | "NOT_RECOMMENDED" | "EVALUATION";
/** Why a pick's state is the one it is. */
export type StatusReason =
  "approved" | "value" | "not_reviewed" | "downgraded" | "rejected" | "no_value_now" | "evaluation";

/** state-v2 of PrediGol Intelligence's decision on a selection (fbi/intel/state_v2.py). */
export type DecisionState = "RECOMMENDED" | "CAUTION" | "WATCH" | "ABSTAIN" | "REJECTED";
/** Where the Picks board takes its numbers and states from (FBI_PICKS_SOURCE, plan PICKS F3). */
export type DecisionSource = "legacy" | "intelligence";

/**
 * What PrediGol Intelligence decided about a selection (`decision-v1`, its newest row). Present only while the board reads
 * Intelligence (`decision_source` is "intelligence"). The card's `p_model` is the calibrated probability then; `p_raw` is the
 * model's own before calibrating, to be shown as «sin calibrar».
 */
export interface PickDecision {
  state: DecisionState;
  /** The reason code state-v2 gives (approved, risk, price_stale, edge_not_validated, ...). */
  reason: string;
  known_at: Iso;
  checkpoint: string;
  /** Null while the market has no champion calibrator. */
  p_calibrated: Dec | null;
  p_raw: Dec;
  ev_calibrated: Dec | null;
  edge_calibrated: Dec | null;
  /** The price Intelligence judged at known_at. */
  odds: Dec | null;
  price_at: Iso | null;
}

/** The state a reader is shown, as every pick that has one carries it. */
export interface PickState {
  user_status: UserStatus;
  status_reason: StatusReason;
  /** RECOMMENDED by the value rule alone: «revisión de contexto aún no aplicada» is said beside it. */
  context_pending: boolean;
}

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
  user_status: UserStatus;
  status_reason: StatusReason;
  context_pending: boolean;
  /** Intelligence's decision on this selection; null when the board does not read it, or it has not decided it. */
  decision?: PickDecision | null;
}

/**
 * A pre-match pick whose match has kicked off: the record as it was taken before kick-off,
 * never re-priced. One per selection - the last pick made before kick-off.
 */
export interface StartedPick {
  pick_id: number;
  fixture_id: number;
  kickoff_at: Iso;
  competition: CompetitionBadge;
  home: TeamBadge;
  away: TeamBadge;
  market_key: string;
  selection: string;
  line: Dec;
  /** What it was before kick-off. */
  status: "shadow" | "qualified" | "published";
  model: string;
  /** When the pick was made, and when its price was captured. */
  created_at: Iso;
  taken_at: Iso;
  odds_taken: Dec;
  bookmaker: string | null;
  p_model: Dec;
  p_market: Dec;
  fair_odds: Dec;
  edge: Dec;
  ev: Dec;
  /** Picks made on this selection before kick-off; this is the last. */
  evaluations: number;
  phase: MatchPhase;
  status_short: string | null;
  live_minute: number | null;
  live_extra: number | null;
  live_home: number | null;
  live_away: number | null;
  /** The 90-minute score, once the match has one. */
  score_home: number | null;
  score_away: number | null;
  /** win, loss, push, void, half_win, half_loss, pending - or null before the match ends. */
  result_status: string | null;
  profit_units: Dec | null;
  settled_at: Iso | null;
  review_reason: string | null;
  /**
   * The same bookmaker's last pre-match price, and odds_taken / near_close_odds - 1: value
   * against a near-close price, not validated as the closing line.
   */
  near_close_odds: Dec | null;
  line_value: Dec | null;
  /** The state a reader is shown for it, read as it was taken (plan PICKS, L1: «solo verde» also after kick-off). */
  user_status?: UserStatus;
  status_reason?: StatusReason;
  context_pending?: boolean;
  /** Intelligence's last decision before kick-off, while the board reads it; `p_model`, `edge` and `ev` use its calibrated p. */
  decision?: PickDecision | null;
}

export interface PicksBoard {
  source: ProductSource;
  top: PickCard[];
  picks: PickCard[];
  competitions: CompetitionBadge[];
  markets: string[];
  window_hours: number;
  reason: string | null;
  /**
   * Published picks of the window a reader is not shown now (plan UX, B3; UX-002): every one that is not RECOMMENDED -
   * without value at the best price now, or downgraded or rejected by the applied AI review -, in a list and on one match
   * alike. 0 in the owner's preview.
   */
  withheld?: number;
  /** Pre-match picks whose match kicked off today (or every one of fixture_id), as taken. */
  started?: StartedPick[];
  /** Where the cards' numbers and states come from; "legacy" when absent. */
  decision_source?: DecisionSource;
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
  /**
   * The line of the market's prices. An Asian handicap's is the HOME side's handicap h: its two prices are one bet, Home at
   * h and Away at -h (each side is quoted at its own line: `selectionLine` in product/odds/board.ts).
   */
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
  /** The highlighted selection's own line: an Asian handicap's away side at -h, the opposite of its market's line. */
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

/** A match that ended in the last 24 hours (plan de Inicio, 3.1). */
export interface HomeResult {
  fixture_id: number;
  kickoff_at: Iso;
  competition: CompetitionBadge;
  home: TeamBadge;
  away: TeamBadge;
  /** Over after 90 minutes, after extra time or after the shoot-out. */
  status: "FT" | "AET" | "PEN";
  goals_home: number;
  goals_away: number;
  /** The shoot-out's score, when there was one. */
  pens_home?: number | null;
  pens_away?: number | null;
}

/**
 * Why a match is on «Partidos relevantes» or «Qué se juega» (plan de Inicio, 3.1b): a code and the values its sentence fills in,
 * chosen on the server. ``final``; ``tie`` (a second leg in play: the aggregate now); ``first_leg`` (a second leg still to be
 * played: how the first ended); ``stakes`` (a side fights for ``pressure``; in play with ``state``); ``comeback``.
 */
export interface HomeReason {
  code: "final" | "tie" | "first_leg" | "stakes" | "comeback";
  params: Record<string, string | number | boolean | null>;
}

/** A match in play with a reason to look at it now (one or two reasons, the strongest first). */
export interface HomeRelevant {
  match: LiveMatch;
  reasons: HomeReason[];
}

/** A match of the next 36 hours with something at stake: one reason. */
export interface HomeAtStake {
  fixture_id: number;
  kickoff_at: Iso;
  competition: CompetitionBadge;
  home: TeamBadge;
  away: TeamBadge;
  reason: HomeReason;
}

export interface Home {
  source: ProductSource;
  data_freshness: { live_at: Iso | null };
  /** In play with a reason, by competition priority, four at most. Absent from an API older than 3.1b. */
  relevant?: Section<HomeRelevant[]>;
  /** Not started, next 36 hours, something at stake, four at most. Absent from an API older than 3.1b. */
  at_stake?: Section<HomeAtStake[]>;
  /** What else is in play: the matches of ``relevant`` are not repeated here. */
  live: Section<LiveMatch[]>;
  /** What ended in the last 24 hours, newest first, six at most. Absent from an API older than 3.1. */
  results?: Section<HomeResult[]>;
}

export interface PicksQuery {
  competition_id?: number | undefined;
  market?: string | undefined;
  min_odds?: number | undefined;
  max_odds?: number | undefined;
  hours?: number | undefined;
  /** One match only, whenever it kicks off or kicked off. */
  fixture_id?: number | undefined;
}

// ── settlement latency (Admin -> Picks) ─────────────────────────────────────

export interface SettlementRow {
  fixture_id: number;
  home: string;
  away: string;
  competition: string;
  kickoff_at: Iso;
  status_short: string;
  /** The last state seen in play: the provider had not finished the match yet. */
  last_in_play_at: Iso | null;
  /** The first state seen ended (or the result row, for a match not followed live). */
  observed_finished_at: Iso | null;
  result_stored_at: Iso | null;
  settled_at: Iso;
  /** settled_at - observed_finished_at. */
  delay_seconds: number | null;
  path: "live_follow" | "results_repair" | "pipeline";
  picks_settled: number;
  items_settled: number;
}

export interface WaitingSettlement {
  fixture_id: number;
  home: string;
  away: string;
  kickoff_at: Iso;
  status_short: string;
  open_picks: number;
  open_items: number;
  ended_at: Iso | null;
  review_reason: string | null;
}

export interface SettlementLatency {
  days: number;
  matches: number;
  mean_seconds: number | null;
  median_seconds: number | null;
  p90_seconds: number | null;
  max_seconds: number | null;
  by_path: Record<string, number>;
  rows: SettlementRow[];
  waiting: WaitingSettlement[];
}
