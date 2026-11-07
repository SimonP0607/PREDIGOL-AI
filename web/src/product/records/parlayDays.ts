/**
 * The days of a multi-day parlay (plan de Inicio, 2.4): its legs are played over several days, so the card says the span in
 * its title and groups the legs under the day each is played - the reader's day, in the reader's time zone.
 */
import { dayKey, formatDate } from "@/lib/time";
import type { ParlayRecordLeg } from "@/lib/api/v1/types_records";

export interface DayGroup<L> {
  /** The reader's calendar day, `2026-11-07`. */
  day: string;
  /** The first leg's kick-off of that day: what the day's label is written from. */
  at: string;
  legs: L[];
}

/** The legs in the order they come, in a group for each day they are played (a day shows once, at its first leg). */
export function groupByDay<L extends Pick<ParlayRecordLeg, "match">>(
  legs: readonly L[],
): DayGroup<L>[] {
  const groups: DayGroup<L>[] = [];
  for (const leg of legs) {
    const at = leg.match.kickoff_at;
    const day = dayKey(at);
    const last = groups[groups.length - 1];
    if (last && last.day === day) last.legs.push(leg);
    else {
      const found = groups.find((g) => g.day === day);
      if (found) found.legs.push(leg);
      else groups.push({ day, at, legs: [leg] });
    }
  }
  return groups;
}

/** «sáb 8 nov – lun 10 nov»; a single day, just that day; none, null. */
export function dayRange(groups: readonly DayGroup<unknown>[]): string | null {
  const first = groups[0];
  const last = groups[groups.length - 1];
  if (!first || !last) return null;
  const a = formatDate(first.at);
  return first.day === last.day ? a : `${a} – ${formatDate(last.at)}`;
}
