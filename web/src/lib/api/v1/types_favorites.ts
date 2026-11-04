/**
 * A reader's favourite leagues and teams, the welcome and the hints (plan UX, A13), as the API returns them. Mirrors
 * fbi.api.contracts.favorites. The favourites order and filter what a reader is shown; they never change a pick, a
 * probability, a state or a price.
 */
import type { CompetitionBadge, TeamBadge } from "./types_product";

export interface FavoritesView {
  /** The leagues the reader follows, in the order chosen. */
  leagues: CompetitionBadge[];
  teams: TeamBadge[];
  /** True while the reader has chosen none: the ones suggested for Colombia, labelled as suggested. */
  suggested: boolean;
  max_leagues: number;
  max_teams: number;
  /** FBI_PERSONALIZATION: false gives every reader the common view (Home without «Hoy en tus ligas»). */
  personalization: boolean;
}

export interface FavoritesIn {
  leagues: number[];
  teams: number[];
}

export interface FavoriteOptions {
  /** Every league PrediGol follows, by country and name. */
  leagues: CompetitionBadge[];
  /** Teams of those leagues whose name matches the search (two letters or more, without accents or case), at most 20. */
  teams: TeamBadge[];
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
