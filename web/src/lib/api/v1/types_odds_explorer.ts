/**
 * Types of the odds explorer (plan Cuotas, ola 2; BE-011): /odds/families, /odds/board, /matches/{id}/odds-book,
 * /odds/fixtures/{id}/movement and /admin/odds/health. Mirrors fbi.api.contracts.odds_explorer, field for field.
 *
 * A market is a stable key the page translates: the tax-v3 key without its period (`corners.total`, `goals.total.home`; a
 * minute interval keeps its own, `result.1x2.m0_10`). Selections are vocabulary codes (Home, Draw, Away, Over, Under, Yes,
 * No, 1X, 12, X2, an exact score "2:1", a band "0-2", "Player" with the player's name in `player`). Bookmaker ids are the
 * PROVIDER's; each answer names the ones it uses in `bookmakers`. Decimals are strings, times ISO-8601 UTC.
 *
 * `state`: `current` when the price was confirmed by the latest scheduled capture or book refresh for its distance to
 * kick-off; `stale` when one was missed - shown dimmed, never parlay-ready, left out of `sort=edge`.
 */
import type { Dec, Iso } from "./types";
import type { CompetitionBadge, TeamBadge } from "./types_product";

export type OddsSubject = "match" | "home" | "away" | "player" | "keeper";
export type OddsPeriod = "FT" | "1H" | "2H" | "INTERVAL";
export type OddsRowState = "current" | "stale";
export type OddsBookState = "current" | "stale" | "none";
export type OddsHorizon = "0-6h" | "6-24h" | "24-72h";
export type OddsBoardSort = "time" | "competition" | "edge";

export interface OddsMarketInfo {
  /** Stable key: the tax-v3 key without its period (corners.total, goals.total.home). */
  key: string;
  /** The family it is listed under (result, goals, goals_half, corners, cards, shots, players ...). */
  family: string;
  /**
   * How its selections read (the tax-v3 reader): plain, line, signed_line, signed_line_3way, exact_score, ht_ft,
   * result_total, total_btts, count, range, player, player_count.
   */
  kind: string;
  subject: OddsSubject;
  /** The periods with prices (in the window, or in the match). */
  periods: OddsPeriod[];
  has_line: boolean;
  /** A fair price can be computed for it (it still needs three complete bookmakers in a match). */
  fair: boolean;
  /** One of its periods is one of Mi Parlay's five markets. */
  parlay: boolean;
  /** Matches with prices for it (in the window; 1 in a match's book). */
  fixtures: number;
  /** The most bookmakers quoting it in one match. */
  max_books: number;
}

export interface OddsFamily {
  key: string;
  fixtures: number;
  markets: OddsMarketInfo[];
}

export interface OddsFamilies {
  window_hours: number;
  /** Only the families and markets with prices in the window, in the explorer's order. */
  families: OddsFamily[];
  /** FBI_ODDS_BOOK: the worker builds the book. */
  book_enabled: boolean;
  generated_at: Iso;
}

export interface OddsSelectionPrice {
  /** A vocabulary code; "Player" in a player market, with the name in `player`. */
  selection: string;
  player: string | null;
  /** The selection's OWN line (an Asian handicap's away side is -h); a player count's line is the count reached. */
  line: Dec | null;
  /** The highest price among every bookmaker in force. */
  best_odds: Dec;
  /** The provider bookmaker of the best price. */
  bookmaker_id: number;
  n_books: number;
  /** The market's de-vigged consensus price; null where it means nothing. */
  fair_odds: Dec | null;
  /** best_odds * p_fair - 1, only with fair_odds: a market comparison, not a model's edge. */
  price_edge: Dec | null;
  /** More than 25 % above fair: suspect, never highlighted, never in Mi Parlay. */
  outlier: boolean;
  /** One of Mi Parlay's five markets, not a quarter line, not an outlier, current and not started. */
  parlay_ok: boolean;
}

export interface OddsBoardRow {
  fixture_id: number;
  kickoff_at: Iso;
  competition_id: number;
  home: TeamBadge;
  away: TeamBadge;
  /** The line shown (an Asian handicap's: the home line). */
  line: Dec | null;
  /** Every line this match quotes for the market, sorted. */
  lines: Dec[];
  selections: OddsSelectionPrice[];
  /** When the body in force was first fetched. */
  captured_at: Iso;
  /** The provider's own update stamp of that body. */
  provider_update_at: Iso | null;
  state: OddsRowState;
}

export interface OddsBookmaker {
  /** The provider's bookmaker id. */
  id: number;
  name: string;
}

export interface OddsBoardPage {
  market: OddsMarketInfo;
  period: OddsPeriod;
  rows: OddsBoardRow[];
  /** Rows matching the filters (under sort=edge: current rows with a fair price only). */
  total: number;
  /** Pass back as `cursor` for the next page; null on the last one. */
  next_cursor: string | null;
  /** The competitions of the rows (a dictionary). */
  competitions: CompetitionBadge[];
  /** The bookmakers the rows name (a dictionary). */
  bookmakers: OddsBookmaker[];
  generated_at: Iso;
}

export interface OddsBookPrices {
  bookmaker_id: number;
  /** This bookmaker's price of each selection of the line, in the order of `selections`; null where it does not quote one. */
  odds: (Dec | null)[];
}

export interface OddsBookLine {
  line: Dec | null;
  selections: OddsSelectionPrice[];
  books: OddsBookPrices[];
}

export interface OddsBookMarket {
  info: OddsMarketInfo;
  period: OddsPeriod;
  /** The line shown first (null without lines). */
  main_line: Dec | null;
  lines: OddsBookLine[];
}

export interface OddsBookFamily {
  key: string;
  markets: OddsBookMarket[];
}

export interface MatchOddsBook {
  fixture_id: number;
  kickoff_at: Iso;
  captured_at: Iso | null;
  provider_update_at: Iso | null;
  /** none: no price in force (never asked, withdrawn, or not built). */
  state: OddsBookState;
  families: OddsBookFamily[];
  bookmakers: OddsBookmaker[];
}

export interface OddsMovementPoint {
  /** The capture's instant. */
  at: Iso;
  /** The best price at that capture, outliers left out. */
  best_odds: Dec;
  bookmaker_id: number;
  n_books: number;
}

export interface OddsMovementSeries {
  selection: string;
  /** The selection's own line (an Asian handicap's away side: -h). */
  line: Dec | null;
  points: OddsMovementPoint[];
}

export interface OddsMovement {
  fixture_id: number;
  market: string;
  period: OddsPeriod;
  /** The line followed (the market's main line when none was asked for). */
  line: Dec | null;
  /** False for a type with no stored history (only the five classic markets and the 55 extracted types have one). */
  available: boolean;
  source: "snapshots" | "quotes" | null;
  series: OddsMovementSeries[];
  bookmakers: OddsBookmaker[];
}

export interface OddsHorizonHealth {
  horizon: OddsHorizon;
  /** Followed matches with odds kicking off in the horizon. */
  fixtures: number;
  with_book: number;
  /** Median minutes since the ask that confirmed their prices. */
  median_age_min: number | null;
  /** Those whose prices missed a scheduled capture or refresh. */
  stale: number;
}

export interface OddsHealth {
  by_horizon: OddsHorizonHealth[];
  /** Age of the oldest /odds body of the last day the extractor has not read (0: caught up). */
  extraction_lag_min: number | null;
  book_rows: number;
  book_mb: number;
  /** Requests issued today, counted by us. */
  quota_today: number;
  /** Our daily budget, never above the plan. */
  quota_limit: number;
  /** What the provider's headers said remains today; null before any answer of the day carried it. */
  provider_requests_remaining: number | null;
  /** Rows in the DEFAULT partitions of the odds series (should be 0). */
  default_partition_rows: number;
  odds_quotes_gb: number;
  /** FBI_QUOTES_MAX_TABLE_GB: the extractor stops past it. */
  odds_quotes_brake_gb: number;
}

/** GET /odds/families. */
export interface OddsFamiliesQuery {
  /** Matches kicking off in the next N hours: 24, 48 or 72 on the page (1 to 72). */
  hours?: number | undefined;
  /** The competition's country, as it is named. */
  country?: string | undefined;
  /** A competition id. */
  competition?: number | undefined;
}

/** GET /odds/board. The cursor is the infinite query's page parameter (useOddsBoard). */
export interface OddsBoardQuery extends OddsFamiliesQuery {
  /** A market key of /odds/families. */
  market: string;
  period?: OddsPeriod | undefined;
  /** A line (an Asian handicap's: the home line), or "main": each match's main line (the default). */
  line?: string | undefined;
  /** Part of a team's or a competition's name. */
  q?: string | undefined;
  /** The provider's bookmaker id: only the matches it quotes at the line shown. */
  bookmaker?: number | undefined;
  min_books?: number | undefined;
  odds_min?: string | undefined;
  odds_max?: string | undefined;
  fair_only?: boolean | undefined;
  sort?: OddsBoardSort | undefined;
  limit?: number | undefined;
}

/** GET /matches/{id}/odds-book. */
export interface MatchOddsBookQuery {
  /** One family of the book; none: every family. */
  family?: string | undefined;
}

/** GET /odds/fixtures/{id}/movement. */
export interface OddsMovementQuery {
  market: string;
  period?: OddsPeriod | undefined;
  /** A line (an Asian handicap's: the home line); none: the market's main line. */
  line?: string | undefined;
}

/** «Estado de los precios» (GET /odds/status, behind FBI_ODDS_STATUS): what a reader may know of the prices they see. */
export interface OddsStatusHorizon {
  horizon: "0-6h" | "6-24h" | "24-72h";
  /** Followed matches with odds kicking off in the horizon. */
  fixtures: number;
  with_price: number;
  /** Those whose price missed a scheduled capture. */
  stale: number;
}

export interface OddsStatusMatch {
  fixture_id: number;
  kickoff_at: string;
  home: string;
  away: string;
  competition: string;
}

export interface OddsStatus {
  last_read_at: string | null;
  by_horizon: OddsStatusHorizon[];
  /** Followed matches of the next 24 h without a price in force, soonest first (at most 20). */
  without_price: OddsStatusMatch[];
  without_price_total: number;
  /** Minutes before kick-off at which a price is read again. */
  schedule_minutes: number[];
  tolerance_minutes: number;
}
