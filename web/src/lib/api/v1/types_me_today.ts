/**
 * «Para ti», the reader's layer of Home (closing plan 3.2), as the API returns it. Mirrors fbi.api.contracts.me_today: the
 * players the reader follows with the state of the next match of his team, which of the day's published picks are of their
 * matches or markets, and their notices. The favourites order and label: no pick, probability or price changes.
 */
import type { Iso } from "./types";
import type { CompetitionBadge, TeamBadge } from "./types_product";
import type { FollowReason } from "./types_today";

export type MarketKey = "1X2" | "OU" | "BTTS" | "AH" | "DC";

/**
 * starter / bench: in the published line-up of the next match of his team; left_out: the line-up is out and he is not in it;
 * absent / doubtful: the provider's current absences name him; waiting: no line-up and no report yet; no_match: his team has
 * no match to come in the next 120 days.
 */
export type PlayerState =
  "starter" | "bench" | "left_out" | "absent" | "doubtful" | "waiting" | "no_match";

export interface PlayerMatch {
  fixture_id: number;
  kickoff_at: Iso;
  competition: CompetitionBadge;
  home: TeamBadge;
  away: TeamBadge;
}

export interface WatchedPlayer {
  /** core.players id. */
  id: number;
  name: string;
  position: string | null;
  /** His side of the match below; null without a match to come. */
  team: TeamBadge | null;
  state: PlayerState;
  /** absent / doubtful: the provider's own words (the page classifies them as the match's «Bajas» do). */
  reason: string | null;
  next: PlayerMatch | null;
}

export interface RelatedPick {
  /** The pick's rank in the day's published set: the card Home already shows (GET /daily). */
  rank: number;
  fixture_id: number;
  market_key: MarketKey;
  /** Why its match is the reader's; null when only its market is. */
  followed: FollowReason | null;
  market_followed: boolean;
}

export interface RelatedPicks {
  day: string;
  /** How many picks of the day a reader is shown. 0: the day has none, whatever the reader follows. */
  published: number;
  /** Those that are of the reader's matches or markets, in the set's order. */
  items: RelatedPick[];
}

export interface MatchBell {
  fixture_id: number;
  kickoff_at: Iso;
  /** 15, 30 or 60. */
  minutes_before: number;
  competition: CompetitionBadge;
  home: TeamBadge;
  away: TeamBadge;
}

export interface Notices {
  /** Notices can be offered at all (FBI_PUSH on and the VAPID key set). */
  available: boolean;
  /** The reader's devices that receive notices now. */
  devices: number;
  /** Their «alineaciones» category is on. */
  lineup: boolean;
  bells: MatchBell[];
}

export interface MeToday {
  /** False: the common view - Home has its PrediGol layer alone. */
  personalization: boolean;
  /** The reader chose a league, a team, a player or a market (the suggested ones never count) and personalisation is on. */
  chosen: boolean;
  players: WatchedPlayer[];
  markets: MarketKey[];
  picks: RelatedPicks | null;
  notices: Notices | null;
}
