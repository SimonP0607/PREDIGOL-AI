/** The Picks page filters and the API query they make. Pure: no React here. */
import type { PicksQuery } from "@/lib/api/v1/types_product";

export type OddsRange = "all" | "1.5-2" | "2-3" | "3+";

export interface PickFilters {
  /** The name is kept so the choice still reads right if the window no longer has that competition. */
  competition: { id: number; name: string } | null;
  market: string | null;
  odds: OddsRange;
  hours: number;
}

/** The page's default window: the earliest matches first (REVIEW PREDIGOL, point 13: 24 h, not 72 h). */
export const DEFAULT_HOURS = 24;

/** The API's own default window: a query that asks for it can leave it out. */
export const API_DEFAULT_HOURS = 72;

export const DEFAULT_FILTERS: PickFilters = {
  competition: null,
  market: null,
  odds: "all",
  hours: DEFAULT_HOURS,
};

export const ODDS_RANGES: Record<OddsRange, { min?: number; max?: number }> = {
  all: {},
  "1.5-2": { min: 1.5, max: 2 },
  "2-3": { min: 2, max: 3 },
  "3+": { min: 3 },
};

export const ODDS_RANGE_KEYS: readonly OddsRange[] = ["all", "1.5-2", "2-3", "3+"];

/** Kick-off windows in hours: 24 h, 48 h, 72 h and 7 days. */
export const WINDOWS: readonly number[] = [24, 48, 72, 168];

/** The API query for these filters. The API's own defaults are left out. */
export function toQuery(f: PickFilters): PicksQuery {
  const q: PicksQuery = {};
  if (f.competition) q.competition_id = f.competition.id;
  if (f.market) q.market = f.market;
  const range = ODDS_RANGES[f.odds];
  if (range.min !== undefined) q.min_odds = range.min;
  if (range.max !== undefined) q.max_odds = range.max;
  if (f.hours !== API_DEFAULT_HOURS) q.hours = f.hours;
  return q;
}

/** Nothing chosen beyond the page's own defaults. */
export function isDefault(f: PickFilters): boolean {
  return (
    f.competition === null &&
    f.market === null &&
    f.odds === DEFAULT_FILTERS.odds &&
    f.hours === DEFAULT_FILTERS.hours
  );
}
