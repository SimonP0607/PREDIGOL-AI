/**
 * The calendar of a match (plan F4), as the API returns it: what each team has played and has coming, in EVERY
 * competition it plays, and how sure that is. Mirrors fbi.api.contracts.match_calendar.
 *
 * It is context for a reader, never a price or a pick. A side is `complete` only when the list the provider gives for
 * the team was read lately and no match is left unconfirmed; otherwise the figures are what PrediGol could see (rest is
 * at most what they show, the matches at least) and `reason` says why.
 */
import type { Iso } from "./types";

export type CalendarReason = "never_fetched" | "stale" | "unconfirmed_match";
/** provider_calendar: both sides stand on the team's whole list. tracked_competitions: at least one is only what PrediGol follows. */
export type CalendarScope = "provider_calendar" | "tracked_competitions";

export interface CalendarMatch {
  provider_fixture_id: number;
  kickoff_at: Iso;
  /** Days before the match of the page (a match already played) or after it (a match to come). */
  days: number;
  competition: string;
  /** domestic_league, domestic_cup, continental, international; null for a competition PrediGol has never been told about. */
  competition_type: string | null;
  country: string | null;
  round: string | null;
  /** Was the team at home. */
  home: boolean;
  opponent: string | null;
  /** From the team's side ("2-1"), once the match is played and its score is known. */
  result: string | null;
  /** One of the competitions PrediGol follows; the rest are known only from the team's list. */
  followed: boolean;
}

export interface TeamCalendar {
  team_id: number;
  team: string;
  complete: boolean;
  reason: CalendarReason | null;
  /** When the team's list was last read (null: never). */
  fetched_at: Iso | null;
  age_hours: number | null;
  /** Days between the last match played and this one (null: none known). */
  rest_days: number | null;
  matches_last_7d: number;
  matches_last_14d: number;
  matches_last_30d: number;
  /** Of the matches of the last fortnight, those in a competition PrediGol does not follow. */
  outside_last_14d: number;
  /** The last matches played before this one, newest first. */
  recent: CalendarMatch[];
  /** The next matches within the week after this one, soonest first. */
  upcoming: CalendarMatch[];
}

export interface MatchCalendar {
  fixture_id: number;
  kickoff_at: Iso;
  status_group: string;
  /** Both sides are complete. */
  complete: boolean;
  scope: CalendarScope;
  home: TeamCalendar;
  away: TeamCalendar;
}
