/**
 * A reader's favourite leagues, teams, players and markets, the welcome and the hints (plan UX, A13 and 3.1), as the API
 * returns them. Mirrors fbi.api.contracts.favorites. The favourites order and filter what a reader is shown; they never
 * change a pick, a probability, a state or a price.
 */
import type { CompetitionBadge, TeamBadge } from "./types_product";
import type { MarketKey } from "./types_records";

/** A player the reader follows or can follow: the id the line-ups carry (`player_id`). */
export interface PlayerBadge {
  id: number;
  name: string;
  position: string | null;
  /** The team of the player's latest line-up in a league PrediGol follows, to tell two of one name apart. */
  team: string | null;
}

export interface FavoritesView {
  /** The leagues the reader follows, in the order chosen. */
  leagues: CompetitionBadge[];
  teams: TeamBadge[];
  /** The players the reader follows, in the order chosen. */
  players: PlayerBadge[];
  /** The markets the reader follows (the ones they read most), in the order chosen. */
  markets: MarketKey[];
  /**
   * The markets of a match's catalogue the reader follows (`corners_over_under.FT.match`: code, period, subject), in the
   * order chosen (CUOTAS, BE-025). Apart from `markets`, the five classic ones. Absent from an older API.
   */
  catalog_markets?: string[];
  /** True while the reader has chosen none: the ones suggested for Colombia, labelled as suggested. */
  suggested: boolean;
  max_leagues: number;
  max_teams: number;
  max_players: number;
  max_markets: number;
  max_catalog_markets?: number;
  /** FBI_PERSONALIZATION: false gives every reader the common view (Home without «Hoy en tus ligas»). */
  personalization: boolean;
}

export interface FavoritesIn {
  leagues: number[];
  teams: number[];
  /** Left out: the players the reader follows stay (a page from before 3.1 never clears them); [] clears them. */
  players?: number[];
  /** Left out: the markets the reader follows stay; [] clears them. */
  markets?: MarketKey[];
  /** Left out: the catalogue markets the reader follows stay (a page from before BE-025 never clears them); [] clears them. */
  catalog_markets?: string[];
}

export interface FavoriteOptions {
  /** Every league PrediGol follows, by country and name. */
  leagues: CompetitionBadge[];
  /** Teams of those leagues whose name matches the search (two letters or more, without accents or case), at most 20. */
  teams: TeamBadge[];
  /** Players who appeared in a line-up of those leagues whose name matches the search (three letters or more), at most 20. */
  players: PlayerBadge[];
}

export type WelcomeStep = "football" | "about";
export type HintKey = "picks" | "match" | "parlay" | "my_picks";

export interface OnboardingState {
  welcome_due: boolean;
  /** football: the favourites; about: «Qué es PrediGol» - only for a new account. */
  welcome_steps: WelcomeStep[];
  onboarded_at: string | null;
  hints_seen: string[];
}
