/**
 * The odds explorer's data as the UI takes it (plan Cuotas, ola 3; contract SPEC_EXPLORADOR.md, shared with BE-011).
 *
 * These are LOCAL types, structurally identical to the API's mirror (`web/src/lib/api/v1/types_odds_explorer.ts`, owned by
 * BE-011): the same names and fields, decimals as strings ("1.95") and instants as ISO-8601 UTC strings, so an API answer is
 * handed straight in once the hooks exist. The UI never imports `lib/api` until the wiring step. What it needs from the data
 * layer is `ExplorerData` below: one hook per endpoint, which the wiring implements with react-query (`useOddsFamilies`,
 * `useOddsBoard`, `useMatchOddsBook`, `useOddsMovement`) and the tests with `fake.ts`.
 */

/** A decimal as the API sends it: text, never a float. */
export type Dec = string;
/** An ISO-8601 UTC instant. */
export type Iso = string;

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

// ── GET /odds/families ──────────────────────────────────────────────────────────────────────────────────────────────

export interface OddsMarketInfo {
  /** The stable tax-v3 key of the market, without its period: "corners.total", "player.anytime_scorer". */
  key: string;
  family: string;
  kind: string;
  subject: "match" | "home" | "away" | "player" | "keeper";
  /** A subset of "FT", "1H", "2H", "INTERVAL". */
  periods: string[];
  has_line: boolean;
  /** A fair price can be worked out at all (exhaustive selections with a method; it still needs 3 complete bookmakers). */
  fair: boolean;
  /** One of the five markets Mi Parlay takes. */
  parlay: boolean;
  fixtures: number;
  max_books: number;
}

export interface OddsFamily {
  key: string;
  fixtures: number;
  markets: OddsMarketInfo[];
}

/** Only the families and markets with prices in the window. */
export interface OddsFamilies {
  window_hours: number;
  families: OddsFamily[];
  book_enabled: boolean;
  generated_at: Iso;
}

// ── GET /odds/board ─────────────────────────────────────────────────────────────────────────────────────────────────

export interface OddsSelectionPrice {
  /** A vocabulary code: "Home", "Draw", "Away", "Over", "Under", "Yes", "No", an exact score "2:1"... */
  selection: string;
  /** The player of a player prop. */
  player: string | null;
  /** The selection's OWN line: an Asian handicap's away side is at -h. */
  line: Dec | null;
  best_odds: Dec;
  bookmaker_id: number;
  n_books: number;
  fair_odds: Dec | null;
  /** best_odds · p_fair - 1, only with fair_odds. */
  price_edge: Dec | null;
  outlier: boolean;
  /** A classic market, not a quarter line, not an outlier, the row not stale and the match not started. */
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
  /** Every line this row has, sorted. */
  lines: Dec[];
  selections: OddsSelectionPrice[];
  captured_at: Iso;
  provider_update_at: Iso | null;
  /** "stale": a scheduled capture or refresh was missed (the shared freshness rule). */
  state: "current" | "stale";
}

export interface BookmakerRef {
  id: number;
  name: string;
}

export interface OddsBoardPage {
  market: OddsMarketInfo;
  period: string;
  rows: OddsBoardRow[];
  total: number;
  next_cursor: string | null;
  /** The dictionary of the rows' competitions. */
  competitions: CompetitionBadge[];
  bookmakers: BookmakerRef[];
  generated_at: Iso;
}

// ── GET /matches/{id}/odds-book ─────────────────────────────────────────────────────────────────────────────────────

export interface OddsBookLine {
  line: Dec | null;
  selections: OddsSelectionPrice[];
  /** Each bookmaker's odds, in the order of `selections` (null: it does not quote that one). */
  books: Array<{ bookmaker_id: number; odds: Array<Dec | null> }>;
}

export interface OddsBookMarket {
  info: OddsMarketInfo;
  period: string;
  main_line: Dec | null;
  lines: OddsBookLine[];
}

export interface MatchOddsBook {
  fixture_id: number;
  kickoff_at: Iso;
  captured_at: Iso | null;
  provider_update_at: Iso | null;
  state: "current" | "stale" | "none";
  families: Array<{ key: string; markets: OddsBookMarket[] }>;
  bookmakers: BookmakerRef[];
}

// ── GET /admin/odds/health (the owner's panel; not read by the explorer) ───────────────────────────────────────────

export interface OddsHealth {
  by_horizon: Array<{
    horizon: "0-6h" | "6-24h" | "24-72h";
    fixtures: number;
    with_book: number;
    median_age_min: number | null;
    stale: number;
  }>;
  extraction_lag_min: number | null;
  book_rows: number;
  book_mb: number;
  quota_today: number;
  quota_limit: number;
  provider_requests_remaining: number | null;
  default_partition_rows: number;
  odds_quotes_gb: number;
  odds_quotes_brake_gb: number;
}

// ── GET /odds/fixtures/{id}/movement ────────────────────────────────────────────────────────────────────────────────

/**
 * The spec fixes the endpoint («series of the best odds per selection over the stored history, outliers excluded;
 * `available: false` for types without history») but not the field names: these are the explorer's reading of it, to be
 * matched (or mapped in the hook) when BE-011 publishes its contract.
 */
export interface OddsMovementPoint {
  captured_at: Iso;
  best_odds: Dec;
  bookmaker_id: number;
}

export interface OddsMovementSeries {
  selection: string;
  player: string | null;
  line: Dec | null;
  points: OddsMovementPoint[];
}

export interface OddsMovement {
  fixture_id: number;
  market: string;
  period: string;
  line: Dec | null;
  /** False for a type without stored history: nothing to draw. */
  available: boolean;
  series: OddsMovementSeries[];
  bookmakers: BookmakerRef[];
}

// ── what the explorer asks the data layer for ───────────────────────────────────────────────────────────────────────

export type BoardSort = "time" | "competition" | "edge";

/** GET /odds/families. `hours` is 24, 48 or 72 (the «Hoy» window asks for 24 and keeps today's rows). */
export interface FamiliesQuery {
  hours: number;
  /** A competition's country as the badges name it ("England"); null: every country. */
  country: string | null;
  competition: number | null;
}

/** GET /odds/board: the API's own parameter names, so the wiring passes them through (cursor and limit are the hook's). */
export interface BoardQuery extends FamiliesQuery {
  market: string;
  period: string;
  /** "main", or a decimal ("2.5", "-0.25"). */
  line: string;
  /** Team or competition names. */
  q: string;
  bookmaker: number | null;
  min_books: number | null;
  odds_min: Dec | null;
  odds_max: Dec | null;
  fair_only: boolean;
  sort: BoardSort;
}

export interface MovementQuery {
  market: string;
  period: string;
  line: Dec | null;
}

/** How a live hook refreshes. */
export interface LiveOptions {
  /** «Pausar actualizaciones» (WCAG 2.2.2): no refetch on a timer while true. */
  paused: boolean;
  /** False: nothing to ask yet (the families have not said which market there is). */
  enabled: boolean;
}

/** react-query's answer, reduced to what the explorer reads. */
export interface Loadable<T> {
  data: T | undefined;
  /** Nothing to show yet: the first load. */
  isPending: boolean;
  /** The last fetch failed; `data`, when there is some, is the previous answer. */
  isError: boolean;
  error: unknown;
  /** A fetch is running: a refresh, or another query's while the previous data stays on screen. */
  isFetching: boolean;
  /** The data on show is the previous query's, kept while this one loads (keepPreviousData). */
  isPlaceholderData: boolean;
  /** When the data on show arrived, in ms since the epoch; 0 without data. */
  updatedAt: number;
  refetch: () => void;
}

/** The board's cursor pages: «Cargar más» appends the next one. */
export interface BoardPages extends Loadable<OddsBoardPage[]> {
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  fetchNextPage: () => void;
}

/** The reader's teams and leagues (product/favorites' FollowSet fits): «Mis equipos y ligas». */
export interface ExplorerFollow {
  teams: ReadonlySet<number>;
  leagues: { has(id: number): boolean };
}

/**
 * The explorer's data layer: one hook per endpoint. Each member is called as a hook (unconditionally, in the same order on
 * every render), so the wiring can implement it with react-query; the object itself must be stable (a module constant).
 */
export interface ExplorerData {
  useFamilies(q: FamiliesQuery, live: LiveOptions): Loadable<OddsFamilies>;
  useBoard(q: BoardQuery, live: LiveOptions): BoardPages;
  /** Asked only while a row's «Comparar casas» is open. */
  useMatchBook(fixtureId: number, family: string, enabled: boolean): Loadable<MatchOddsBook>;
  /** Asked only while a row's «Movimiento» is open. */
  useMovement(fixtureId: number, q: MovementQuery, enabled: boolean): Loadable<OddsMovement>;
  /** Null while unknown or with personalisation off: «Mis equipos y ligas» is not offered then. */
  useFollow(): ExplorerFollow | null;
}
