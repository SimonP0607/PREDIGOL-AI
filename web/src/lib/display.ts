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
let pricesOff = false;

/**
 * «Solo fútbol» or a pause (plan PM, PM-14-07; FBI_WELLBEING): while it runs this reader sees no price. The account says it (`/auth/me`,
 * `wellbeing.active`) and the provider sets it here before anything is drawn, as it does the display; `formatOdds` - the one way
 * any screen writes a price - then writes none. Not on the owner's console (`/admin`), which is not a reader's screen.
 */
export function setPricesOff(off: boolean): void {
  pricesOff = off;
}

/** Whether a price is not to be written now (see `setPricesOff`). */
export function pricesAreOff(): boolean {
  if (!pricesOff) return false;
  return !(typeof window !== "undefined" && window.location.pathname.startsWith("/admin"));
}

export function setDisplay(next: Partial<Display> | null | undefined): void {
  current = { ...DEFAULT_DISPLAY, ...(next ?? {}) };
}

export function getDisplay(): Display {
  return current;
}

/** What tells one way of drawing from another: the root remounts the pages when it changes. */
export function displayKey(d: Display = current, prices: boolean = pricesOff): string {
  return `${d.time_format}|${d.odds_format}${prices ? "|sinprecios" : ""}`;
}
