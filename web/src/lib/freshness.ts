/**
 * When a reader is told that data is late (plan UX, AP-I02, decision D16).
 *
 * A «updated N minutes ago» line on every screen is noise: it says nothing while the data is fine and a reader learns to
 * ignore it. So the reader hears about it only when it matters, with one sentence; the administrator, who has to judge the
 * pipeline, always sees the exact hour. The thresholds live HERE and nowhere else (sheet S9 of the canvas):
 *
 *   live    the score of a match in play, older than 5 minutes
 *   day     the day's data (prices, fixtures), older than 60 minutes
 *
 * The time that sits beside each price (C5, D4) is information about the price and does not go through here.
 */

export type FreshnessKind = "live" | "day";

/** Older than this (ms), data of that kind is late. */
export const DELAY_AFTER_MS: Record<FreshnessKind, number> = {
  live: 5 * 60_000,
  day: 60 * 60_000,
};

function toMs(value: string | number | Date | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const ms =
    value instanceof Date ? value.getTime() : typeof value === "number" ? value : Date.parse(value);
  return Number.isFinite(ms) ? ms : null;
}

/** How old the data is (ms), null when its time is not known: nothing is claimed about what it cannot tell. */
export function ageMs(
  asOf: string | number | Date | null | undefined,
  now: number = Date.now(),
): number | null {
  const at = toMs(asOf);
  return at === null ? null : Math.max(0, now - at);
}

/** True only when the data's time is known and past its kind's threshold. */
export function isDelayed(
  kind: FreshnessKind,
  asOf: string | number | Date | null | undefined,
  now: number = Date.now(),
): boolean {
  const age = ageMs(asOf, now);
  return age !== null && age > DELAY_AFTER_MS[kind];
}

/**
 * Whether the line about the data's age is shown. A reader sees it only when the data is late; an administrator always.
 */
export function showFreshness(
  kind: FreshnessKind,
  asOf: string | number | Date | null | undefined,
  admin: boolean,
  now: number = Date.now(),
): boolean {
  return admin || isDelayed(kind, asOf, now);
}
