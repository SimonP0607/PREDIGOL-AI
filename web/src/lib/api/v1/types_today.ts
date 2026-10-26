/**
 * Today, for Home (plan UX, A9 and A13), as the API returns it. Mirrors fbi.api.contracts.today: the matches from 48 hours ago
 * to 36 ahead with PrediGol's result forecast labelled, one line of the reading and the context of the reader's own ones still
 * to be played; the reader's leagues and teams - the suggested ones while they chose none, labelled - with why each of their
 * matches is theirs and the next match of each favourite; and the day's picks state - or why there is none. The favourites
 * order and filter: forecasts, lines, picks and states are the same for every reader.
 */
import type { Dec, Iso, Section } from "./types";
import type { CompetitionBadge, TeamBadge } from "./types_product";
import type { ReadingFact } from "./types_reading";

export interface TodayForecast {
  outcome: "home" | "draw" | "away";
  probability: Dec;
  /** False: the model's own number, labelled «sin calibrar». */
  calibrated: boolean;
}

/** Why a match is the reader's (plan section 38: «siempre explicable»). */
export interface FollowReason {
  /** team: a team the reader follows plays it (said first: the nearer reason); league: it belongs to a followed league. */
  kind: "team" | "league";
  /** The followed team - both, home first, when the reader follows the two - or the league. */
  names: string[];
}

export interface TodayMatch {
  fixture_id: number;
  kickoff_at: Iso;
  status_group: string;
  status: string | null;
  elapsed: number | null;
  goals_home: number | null;
  goals_away: number | null;
  competition: CompetitionBadge;
  home: TeamBadge;
  away: TeamBadge;
  suggested: boolean;
  forecast: TodayForecast | null;
  headline: ReadingFact | null;
  has_reading: boolean;
  /**
   * Home's «Contexto» (plan section 24, block 5), for the reader's own matches still to be played: what is at stake (the
   * table or the tie), the rest and the next match, as the reading's facts. Empty for the rest.
   */
  context: ReadingFact[];
  /** Why the match is the reader's - a followed team or league (the suggested ones while they chose none). Null: not theirs. */
  followed?: FollowReason | null;
}

export type NoPickState = "picks" | "reviewing" | "none";

export interface NoPick {
  /** The product day (America/Bogota) the picks belong to. */
  day: string;
  state: NoPickState;
  /** none: the furthest stage the day's selections reached; null when there was no selection at all. */
  stage: string | null;
  /** none: the commonest reason at that stage, or no_matches / no_qualified_candidates. */
  reason: string | null;
  matches: number;
}

/** The next match of a favourite (one name: that team or league). */
export interface NextFixture {
  followed: FollowReason;
  fixture_id: number;
  kickoff_at: Iso;
  competition: CompetitionBadge;
  home: TeamBadge;
  away: TeamBadge;
}

export interface Following {
  /** True while the reader has chosen none - or personalisation is off: the suggested ones, labelled as suggested. */
  suggested: boolean;
  /** FBI_PERSONALIZATION: false gives every reader the common view (the suggested ones), whatever they follow. */
  personalization: boolean;
  leagues: CompetitionBadge[];
  teams: TeamBadge[];
  /** The next match of each followed league and team, from now and within 120 days, kick-off order. */
  next: NextFixture[];
}

export interface Today {
  day: string;
  suggested: CompetitionBadge[];
  suggested_team: string | null;
  matches: Section<TodayMatch[]>;
  no_pick: Section<NoPick>;
  /** The reader's own leagues and teams (A13): always present on GET /today. */
  following?: Following | null;
}
