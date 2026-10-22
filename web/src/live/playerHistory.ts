/** The history of a player (plan F3): streaks at clubs and the record with his senior national team. */
import type { PlayerClubSpell, PlayerNationalCap } from "@/lib/api/v1/types_center";

export type CapRole = "started" | "cameOn" | "unused" | "waiting";

/** What a squad entry was: he played from the start, came on, stayed on the bench, or the statistics have not arrived yet. */
export function capRole(cap: Pick<PlayerNationalCap, "appeared" | "is_starter">): CapRole {
  if (cap.appeared === null) return "waiting";
  if (!cap.appeared) return "unused";
  return cap.is_starter ? "started" : "cameOn";
}

export interface CapRecord {
  /** Squad entries. */
  squads: number;
  /** Matches he played. */
  caps: number;
  starts: number;
  minutes: number;
  /** Entries whose statistics have not arrived: not counted as played nor as unused. */
  waiting: number;
}

export function capRecord(rows: readonly PlayerNationalCap[]): CapRecord {
  const out: CapRecord = { squads: rows.length, caps: 0, starts: 0, minutes: 0, waiting: 0 };
  for (const r of rows) {
    if (r.appeared === null) out.waiting += 1;
    else if (r.appeared) {
      out.caps += 1;
      if (r.is_starter) out.starts += 1;
      out.minutes += r.minutes ?? 0;
    }
  }
  return out;
}

/** "2:1" from the point of view of the national team; null while the result is not stored. */
export function capScore(
  cap: Pick<PlayerNationalCap, "goals_for" | "goals_against">,
): string | null {
  return cap.goals_for === null || cap.goals_against === null
    ? null
    : `${cap.goals_for}:${cap.goals_against}`;
}

/** The streaks newest first (the API sends them so); a streak with no end is where he is now. */
export function isCurrent(spell: Pick<PlayerClubSpell, "valid_to">): boolean {
  return spell.valid_to === null;
}
