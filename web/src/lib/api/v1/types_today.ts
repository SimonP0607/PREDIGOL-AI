/**
 * Today, for Home (plan UX, A9), as the API returns it. Mirrors fbi.api.contracts.today: the matches from 48 hours ago to 36
 * ahead with PrediGol's result forecast labelled, one line of the reading and the context of the suggested ones still to be
 * played, the suggested leagues until the reader picks theirs (A13), and the day's picks state - or why there is none.
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
   * Home's «Contexto» (plan section 24, block 5), for the suggested matches still to be played: what is at stake (the table
   * or the tie), the rest and the next match, as the reading's facts. Empty for the rest.
   */
  context: ReadingFact[];
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

export interface Today {
  day: string;
  suggested: CompetitionBadge[];
  suggested_team: string | null;
  matches: Section<TodayMatch[]>;
  no_pick: Section<NoPick>;
}
