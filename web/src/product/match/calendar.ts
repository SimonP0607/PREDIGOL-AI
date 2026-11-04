/**
 * CALENDARIO in words (plan F4): what the block shows for a given answer of the API - each team's rest, its
 * matches of the last fortnight, the last it played and the next it plays, and how sure PrediGol is of them. Pure: no
 * React, no fetching.
 *
 * It is context for a reader: days and matches, never a price, a probability or a pick. When a team's list is not
 * whole the words say so (rest is "at most", the matches "at least") instead of showing a figure as if it were the
 * team's real one.
 */
import { t, translateOr } from "@/lib/i18n";
import { localFixed } from "@/lib/i18n/format";
import type { Envelope } from "@/lib/api/v1/types";
import type {
  CalendarMatch,
  CalendarReason,
  MatchCalendar,
  TeamCalendar,
} from "@/lib/api/v1/types_calendar";

/** The block's anchor. */
export const CALENDAR_ID = "team-calendar";

/** The query as the block receives it, apart from React Query so that the block can be rendered from a fixture. */
export type CalendarLoad =
  | { status: "pending" }
  | { status: "error"; error: unknown; retry?: (() => void) | undefined }
  | { status: "success"; envelope: Envelope<MatchCalendar | null> };

export type CalendarScreen =
  /** The owner turned it off for readers (`FBI_CALENDAR_USERS=0`): nothing to show. */
  | { kind: "nothing" }
  | { kind: "loading" }
  | { kind: "error"; error: unknown; retry?: (() => void) | undefined }
  /** The API answered and has no calendar to show (the preview reads it; a user never gets here). */
  | { kind: "none" }
  | { kind: "calendar"; data: MatchCalendar };

/**
 * What the block shows. Readers see it since plan UX A9 (`FBI_CALENDAR_USERS` on unless the owner turns it off), loading
 * and failing included; only an answer that says readers may not see it shows nothing. The preview sees every state.
 */
export function calendarScreen(load: CalendarLoad, preview: boolean): CalendarScreen {
  // Shown to readers since A9 (the owner approved it): a reader sees it load and sees it fail, never a silent gap.
  if (load.status === "pending") return { kind: "loading" };
  if (load.status === "error") return { kind: "error", error: load.error, retry: load.retry };
  const { envelope } = load;
  if (envelope.status !== "ok" || !envelope.data) {
    return preview ? { kind: "none" } : { kind: "nothing" };
  }
  return { kind: "calendar", data: envelope.data };
}

// ── the words ───────────────────────────────────────────────────────────────

/** A number of days as the reader says it: "1 día", "2,3 días", "2 days". */
export function daysText(days: number): string {
  const whole = Number.isInteger(days);
  return t("match.calendar.days", { count: days, days: localFixed(days, whole ? 0 : 1) });
}

/** How far from the match of the page a calendar entry is: "3 días antes" for a match played, "4 días después" for one to come. */
export function distanceText(match: Pick<CalendarMatch, "days">, ahead: boolean): string {
  const days = Math.round(match.days * 10) / 10;
  const whole = Number.isInteger(days);
  const vars = { count: days, days: localFixed(days, whole ? 0 : 1) };
  return ahead ? t("match.calendar.after", vars) : t("match.calendar.before", vars);
}

/** The rest of a side: exact when its calendar is whole, "at most" when it is not (a match not seen would shorten it). */
export function restText(side: Pick<TeamCalendar, "rest_days" | "complete">): string {
  if (side.rest_days === null) return t("match.calendar.restNone");
  const vars = { days: daysText(side.rest_days) };
  return side.complete ? t("match.calendar.restExact", vars) : t("match.calendar.restAtMost", vars);
}

/** The matches of the last fortnight: "3 partidos", "al menos 3 partidos" when the calendar is not whole. */
export function fortnightText(side: Pick<TeamCalendar, "matches_last_14d" | "complete">): string {
  const key = side.complete ? "match.calendar.matches" : "match.calendar.matchesAtLeast";
  return t(key, { count: side.matches_last_14d });
}

/** How many of them were in a competition PrediGol does not follow ("" when none: nothing to add). */
export function outsideText(side: Pick<TeamCalendar, "outside_last_14d">): string {
  return side.outside_last_14d > 0
    ? t("match.calendar.outside", { count: side.outside_last_14d })
    : "";
}

/** "Copa", "Continental"...: PrediGol's own classification where it has one, nothing for a competition it was never told about. */
export function kindLabel(type: string | null): string {
  return type ? translateOr(`match.calendar.kind.${type}`, "") : "";
}

/** "local" / "visitante". */
export function venueLabel(home: boolean): string {
  return home ? t("match.calendar.venue.home") : t("match.calendar.venue.away");
}

/** Why a side's calendar is not whole, in a sentence that names the team. Empty for a side that is whole. */
export function incompleteNote(
  side: Pick<TeamCalendar, "complete" | "reason" | "team" | "age_hours">,
): string {
  if (side.complete || !side.reason) return "";
  const reason: CalendarReason = side.reason;
  const age = side.age_hours === null ? "" : daysText(Math.max(1, Math.round(side.age_hours / 24)));
  return translateOr(
    `match.calendar.note.${reason}`,
    t("match.calendar.note.never_fetched", { team: side.team }),
    { team: side.team, age },
  );
}

/** The team's matches of the page, one line each: where it stands before or after the match, the competition, the rival. */
export function matchTitle(match: Pick<CalendarMatch, "competition" | "round">): string {
  return match.round ? `${match.competition} · ${match.round}` : match.competition;
}

/** "vs Other FC (local)": who it was against and where; nothing when the provider did not name the rival. */
export function opponentText(match: Pick<CalendarMatch, "opponent" | "home">): string {
  if (!match.opponent) return "";
  return `${t("match.calendar.versus", { opponent: match.opponent })} (${venueLabel(match.home)})`;
}
