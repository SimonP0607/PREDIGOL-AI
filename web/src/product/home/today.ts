/**
 * Which matches each block of Inicio shows (plan UX, A9; section 24), from GET /today - one board for every reader, cut
 * here in the reader's own day and time zone. Until the reader picks their leagues (A13) the blocks follow the leagues
 * suggested for Colombia, labelled as suggested.
 *
 *   1  Hoy en las ligas sugeridas   today's matches of the suggested leagues still to finish, in play first
 *   3  Partidos relevantes          3 to 5 of today's matches of the other followed competitions with a reading
 *   5  Qué se juega                 what is at stake in the next suggested matches: table or tie, rest, next match
 *   6  Resultados                   the suggested leagues' results of the last 48 hours
 *
 * Pure: the clock and the zone are arguments, so a test fixes them.
 */
import type { MatchPhase } from "@/lib/api/v1/types";
import type { ReadingFact } from "@/lib/api/v1/types_reading";
import type { TodayMatch } from "@/lib/api/v1/types_today";
import { dayKey, todayKey } from "@/lib/time";
import { matchPhaseOf } from "@/product/matches/status";

/** Rows of block 1 before «Ver todos los partidos». */
export const TODAY_ROWS = 8;
/** Block 3 shows from 3 to 5 matches - fewer when fewer have a reading, none hides it. */
export const RELEVANT_ROWS = 5;
/** Block 5: the next matches with something at stake, and the lines told of each. */
export const CONTEXT_MATCHES = 4;
export const CONTEXT_FACTS = 3;
/** Block 6: the last 48 hours (the API's own window), newest first. */
export const RESULTS_HOURS = 48;
export const RESULTS_ROWS = 6;
/** When the suggested leagues do not play today: their next matches inside the API's window. */
export const NEXT_ROWS = 3;

/** The stored group, as a provider's code, for a match whose code is missing (the same rule then applies to both). */
const GROUP_CODE: Readonly<Record<string, string>> = {
  scheduled: "NS",
  live: "LIVE",
  finished: "FT",
  postponed: "PST",
  cancelled: "CANC",
};

/** The phase every screen shows (fbi.core.match_state, mirrored in matchPhaseOf): a stale copy is «awaiting». */
export function phaseOf(m: TodayMatch, now: number): MatchPhase {
  return matchPhaseOf(m.status ?? GROUP_CODE[m.status_group] ?? null, m.kickoff_at, now);
}

/** In play (a break or a suspension included). */
export function inPlay(m: TodayMatch, now: number): boolean {
  const phase = phaseOf(m, now);
  return phase === "live" || phase === "suspended";
}

/** Over, with its final score. */
export function played(m: TodayMatch, now: number): boolean {
  return phaseOf(m, now) === "finished" && m.goals_home !== null && m.goals_away !== null;
}

function isToday(m: TodayMatch, tz: string, now: number): boolean {
  return dayKey(m.kickoff_at, tz) === todayKey(tz, now);
}

function byKickoff(a: TodayMatch, b: TodayMatch): number {
  return a.kickoff_at.localeCompare(b.kickoff_at) || a.fixture_id - b.fixture_id;
}

/** In play first, then by kick-off; a match postponed or waiting for its result after the ones to come. */
function liveFirst(now: number) {
  const rank = (m: TodayMatch) => {
    if (inPlay(m, now)) return 0;
    return phaseOf(m, now) === "scheduled" ? 1 : 2;
  };
  return (a: TodayMatch, b: TodayMatch) => rank(a) - rank(b) || byKickoff(a, b);
}

export interface SuggestedToday {
  /** Today's suggested matches still to finish (a match in play since yesterday included). */
  rows: TodayMatch[];
  /** How many of today's suggested matches are already over: their results are in block 6. */
  playedToday: number;
  /** None today: the next suggested matches inside the API's window. */
  next: TodayMatch[];
}

/** Block 1. */
export function suggestedToday(
  matches: readonly TodayMatch[],
  tz: string,
  now: number,
): SuggestedToday {
  const suggested = matches.filter((m) => m.suggested);
  const today = suggested.filter((m) => isToday(m, tz, now) || inPlay(m, now));
  const rows = today.filter((m) => !played(m, now)).sort(liveFirst(now));
  const playedToday = today.filter((m) => played(m, now)).length;
  const next =
    today.length === 0
      ? suggested
          .filter((m) => Date.parse(m.kickoff_at) > now && phaseOf(m, now) === "scheduled")
          .sort(byKickoff)
          .slice(0, NEXT_ROWS)
      : [];
  return { rows, playedToday, next };
}

/** Block 3: today's matches of the other followed competitions with a reading, still to finish. */
export function relevantToday(
  matches: readonly TodayMatch[],
  tz: string,
  now: number,
): TodayMatch[] {
  return matches
    .filter(
      (m) =>
        !m.suggested && m.has_reading && (isToday(m, tz, now) || inPlay(m, now)) && !played(m, now),
    )
    .sort(liveFirst(now))
    .slice(0, RELEVANT_ROWS);
}

/** Block 5: the next suggested matches with something to tell of their context, in kick-off order. */
export function contextAhead(matches: readonly TodayMatch[], now: number): TodayMatch[] {
  return matches
    .filter(
      (m) =>
        m.suggested &&
        m.context.length > 0 &&
        Date.parse(m.kickoff_at) > now &&
        phaseOf(m, now) === "scheduled",
    )
    .sort(byKickoff)
    .slice(0, CONTEXT_MATCHES);
}

/** Block 6: the suggested matches over in the last 48 hours, newest first. */
export function recentResults(matches: readonly TodayMatch[], now: number): TodayMatch[] {
  const since = now - RESULTS_HOURS * 3_600_000;
  return matches
    .filter((m) => m.suggested && played(m, now) && Date.parse(m.kickoff_at) >= since)
    .sort((a, b) => byKickoff(b, a))
    .slice(0, RESULTS_ROWS);
}

const STAKES: ReadonlySet<string> = new Set([
  "stakes_pressure",
  "first_leg",
  "tie_outlook",
  "stakes_gap_up",
  "stakes_gap_down",
  "stakes_zone",
]);

/**
 * The lines block 5 tells of a match (plan section 24: «tabla o eliminatoria, descanso y próximo partido»): what is at
 * stake first, then the rest, then the next match - one of each before a second of any - leaving out the line block 1
 * already shows (the headline). The facts come in the API's order (fbi.api.services.reading.GLANCE_CONTEXT).
 */
export function pickContext(
  facts: readonly ReadingFact[],
  headline: ReadingFact | null,
  max: number = CONTEXT_FACTS,
): ReadingFact[] {
  const fresh = facts.filter(
    (f) => !(headline && f.code === headline.code && f.ref === headline.ref),
  );
  const groups = [
    fresh.filter((f) => STAKES.has(f.code)),
    fresh.filter((f) => f.code === "rest_days"),
    fresh.filter((f) => f.code === "next_match"),
  ];
  const out: ReadingFact[] = [];
  for (let round = 0; out.length < max && groups.some((g) => g.length > round); round++) {
    for (const g of groups) {
      const f = g[round];
      if (f && out.length < max) out.push(f);
    }
  }
  return out;
}
