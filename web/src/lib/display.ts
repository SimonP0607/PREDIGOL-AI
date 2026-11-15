/**
 * How the reader wants PrediGol shown (plan maestro UX/UI 2026, decision 8): the clock, the way a price is written and
 * fewer animations. The account says it (GET /auth/me, `display`) and the page's root sets it here before anything is
 * drawn - as it does with the language and the time zone. Presentation only: a format changes how a price or an hour is
 * WRITTEN, never the value, what is computed from it or what is sent to the API (always decimal odds, always ISO times).
 */
export type OddsFormat = "decimal" | "american" | "fractional";
export type TimeFormat = "24h" | "12h";
export type HomeDefault = "mine" | "all";

export interface Display {
  time_format: TimeFormat;
  odds_format: OddsFormat;
  reduce_motion: boolean;
  /** The view Inicio opens on; null: «Para ti» for a reader who follows something. */
  home_default: HomeDefault | null;
}

/** Today's product, exactly: 24 hours, decimal odds, motion as the device says, Inicio by the rule. */
export const DEFAULT_DISPLAY: Display = {
  time_format: "24h",
  odds_format: "decimal",
  reduce_motion: false,
  home_default: null,
};

let current: Display = DEFAULT_DISPLAY;

export function setDisplay(next: Partial<Display> | null | undefined): void {
  current = { ...DEFAULT_DISPLAY, ...(next ?? {}) };
}

export function getDisplay(): Display {
  return current;
}

/** What tells one way of drawing from another: the root remounts the pages when it changes. */
export function displayKey(d: Display = current): string {
  return `${d.time_format}|${d.odds_format}`;
}
